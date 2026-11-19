"""Интеграционные тесты Redis-репозитория на реальном Redis (Testcontainers).

Задача 3.1: CRUD, установка/обновление TTL, отсутствие частичных мутаций
при отказе. Redis поднимается один раз на сессию; при недоступности Docker
тесты пропускаются с понятным сообщением (как в catalog conftest).
"""

from __future__ import annotations

import uuid

import pytest

from app.application.protocols import CartItemNotFound
from app.domain.cart import CartLimitExceeded, QuantityOutOfBounds
from app.infrastructure.cart_repository import cart_key

pytestmark = pytest.mark.redis_integration

U1 = uuid.UUID("11111111-2222-3333-4444-555555555555")
P1 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
P2 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
P3 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")
P4 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000004")
P5 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000005")


@pytest.fixture(scope="session")
def redis_container():
    """Сессионный Redis-контейнер (redis:7-alpine)."""
    from testcontainers.redis import RedisContainer

    try:
        container = RedisContainer("redis:7-alpine")
        container.start()
    except Exception as exc:  # noqa: BLE001 - докладывать о невозможности
        pytest.skip(f"Cannot start Redis container: {exc}")
    yield container
    container.stop()


@pytest.fixture
async def repo(redis_container):
    """Репозиторий к контейнеру Redis; лимит — 3 различных товара."""
    from app.config import settings
    from app.infrastructure.cart_repository import RedisCartRepository
    from app.infrastructure.redis_client import create_client

    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(redis_container.port)
    settings.redis_url = f"redis://{host}:{port}"
    original_limit = settings.max_distinct_items
    settings.max_distinct_items = 3
    client = create_client(settings.redis_url)
    try:
        yield RedisCartRepository(client)
    finally:
        settings.max_distinct_items = original_limit
        await client.delete(cart_key(U1))
        await client.aclose()


async def test_add_and_get(repo):
    await repo.add_item(U1, P1, 2)
    cart = await repo.get(U1)
    assert cart.items[P1].quantity == 2


async def test_get_missing_cart_is_empty(repo):
    cart = await repo.get(U1)
    assert cart.is_empty


async def test_idempotent_add_increments(repo):
    await repo.add_item(U1, P1, 1)
    await repo.add_item(U1, P1, 1)
    cart = await repo.get(U1)
    assert len(cart.items) == 1
    assert cart.items[P1].quantity == 2


async def test_added_at_stable_on_duplicate_add(repo):
    await repo.add_item(U1, P1, 1)
    first = (await repo.get(U1)).items[P1].added_at
    await repo.add_item(U1, P1, 1)
    second = (await repo.get(U1)).items[P1]
    assert second.added_at == first


async def test_set_quantity(repo):
    await repo.add_item(U1, P1, 1)
    cart = await repo.set_quantity(U1, P1, 5)
    assert cart.items[P1].quantity == 5


async def test_set_quantity_missing_404(repo):
    with pytest.raises(CartItemNotFound):
        await repo.set_quantity(U1, P1, 1)


async def test_remove_item(repo):
    await repo.add_item(U1, P1, 1)
    cart = await repo.remove_item(U1, P1)
    assert cart.is_empty


async def test_remove_missing_404(repo):
    with pytest.raises(CartItemNotFound):
        await repo.remove_item(U1, P1)


async def test_clear(repo):
    await repo.add_item(U1, P1, 1)
    await repo.add_item(U1, P2, 1)
    cart = await repo.clear(U1)
    assert cart.is_empty
    assert (await repo.get(U1)).is_empty


async def test_limit_rejected_cart_unchanged(repo):
    """Лимит различных товаров: 409 и корзина без изменений."""
    for pid in (P1, P2, P3):
        await repo.add_item(U1, pid, 1)
    with pytest.raises(CartLimitExceeded):
        await repo.add_item(U1, P4, 1)
    cart = await repo.get(U1)
    assert set(cart.items) == {P1, P2, P3}


async def test_duplicate_add_beyond_max_quantity_rejected(repo):
    from app.config import settings

    await repo.add_item(U1, P1, settings.max_quantity)
    with pytest.raises(QuantityOutOfBounds):
        await repo.add_item(U1, P1, 1)
    assert (await repo.get(U1)).items[P1].quantity == settings.max_quantity


async def test_ttl_set_on_write(repo):
    """TTL устанавливается при записи (volatile-состояние)."""
    from app.infrastructure.cart_repository import cart_key

    await repo.add_item(U1, P1, 1)
    ttl = await repo._client.ttl(cart_key(U1))
    assert 0 < ttl <= 604800


async def test_ttl_refreshed_on_each_write(repo):
    """TTL обновляется при каждой записи (не уменьшается до нуля)."""
    import asyncio

    from app.infrastructure.cart_repository import cart_key

    await repo.add_item(U1, P1, 1)
    ttl_first = await repo._client.ttl(cart_key(U1))
    await asyncio.sleep(2)
    ttl_after_wait = await repo._client.ttl(cart_key(U1))
    await repo.add_item(U1, P1, 1)
    ttl_refreshed = await repo._client.ttl(cart_key(U1))
    assert ttl_after_wait < ttl_first
    assert ttl_refreshed >= ttl_first


async def test_no_partial_mutation_on_failure(repo):
    """Сбой хранилища не оставляет половинных изменений: ошибка отклоняет
    операцию целиком до того, как состояние меняется (лимит/границы)."""
    # Ограничение количества на дубликате отклоняет запись целиком.
    await repo.add_item(U1, P1, 10)
    with pytest.raises(QuantityOutOfBounds):
        await repo.add_item(U1, P1, 10_000)
    assert (await repo.get(U1)).items[P1].quantity == 10
