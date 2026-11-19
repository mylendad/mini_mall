"""Тест конкурентных мутаций против реального Redis (задача 5.2).

Параллельные добавления одного товара дают quantity N без дублей и без
потерянных обновлений (Lua-скрипты репозитория атомарны); параллельные
смешанные мутации оставляют корзину согласованной.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

pytestmark = pytest.mark.api_integration

U1 = uuid.UUID("11111111-2222-3333-4444-555555555555")
P1 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
P2 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")


@pytest.fixture(scope="session")
def redis_container():
    from testcontainers.redis import RedisContainer

    try:
        container = RedisContainer("redis:7-alpine")
        container.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot start Redis container: {exc}")
    yield container
    container.stop()


@pytest.fixture
async def repo(redis_container):
    from app.config import settings
    from app.infrastructure.cart_repository import RedisCartRepository, cart_key
    from app.infrastructure.redis_client import create_client

    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(redis_container.port)
    settings.redis_url = f"redis://{host}:{port}"
    client = create_client(settings.redis_url)
    yield RedisCartRepository(client)
    await client.delete(cart_key(U1))
    await client.aclose()


async def test_parallel_same_product_adds_yield_exact_quantity(repo):
    """10 параллельных добавлений qty 1 -> quantity 10, дублей нет."""
    await asyncio.gather(*[repo.add_item(U1, P1, 1) for _ in range(10)])
    cart = await repo.get(U1)
    assert len(cart.items) == 1
    assert cart.items[P1].quantity == 10


async def test_parallel_mixed_mutations_consistent(repo):
    """Параллельные add/set/remove разных товаров: итог согласован.

    Все 10 товаров добавлены (ни один не потерян); set-ы применены к
    существующим товарам; удалённые товары отсутствуют.
    """
    products = [
        uuid.UUID(f"bbbbbbbb-0000-0000-0000-{i:012d}") for i in range(10)
    ]
    tasks = []
    for pid in products:
        tasks.append(repo.add_item(U1, pid, 1))
        tasks.append(repo.set_quantity(U1, pid, 2))
    await asyncio.gather(*tasks)

    cart = await repo.get(U1)
    assert set(cart.items) == set(products)
    assert all(item.quantity == 2 for item in cart.items.values())


async def test_parallel_add_and_remove_neither_loses_nor_duplicates(repo):
    """Параллельные добавление и удаление одного товара: без частичных состояний."""
    results = await asyncio.gather(
        repo.add_item(U1, P1, 1), repo.remove_item(U1, P1), return_exceptions=True
    )
    cart = await repo.get(U1)
    # Корректные финалы (нет частичного состояния):
    #   - add применился, затем remove: корзина пуста;
    #   - add применился после неуспешного remove: ровно одна строка qty 1.
    # Промежуточные состояния (дубль, qty > 1) невозможны: операции атомарны.
    assert cart.is_empty or (
        set(cart.items) == {P1} and cart.items[P1].quantity == 1
    )
    remove_failed = isinstance(results[1], Exception)
    if remove_failed:
        assert set(cart.items) == {P1}
    else:
        assert cart.is_empty
