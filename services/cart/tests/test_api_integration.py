"""Интеграционные тесты полного HTTP API против реального Redis (задача 5.1).

Приложение создаётся через ``create_app`` (конверт ошибок, middleware),
репозиторий работает с Testcontainer-Redis; Catalog подменён фейком
(его поведение отдельно проверяет test_catalog_stub_integration.py).
Покрываются: жизненный цикл add → get → patch → remove → clear,
TTL-выселение, 409 на лимите, 422 на границах количества, 401 без
заголовка, изоляция пользователей.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.api_integration

U1 = uuid.UUID("11111111-2222-3333-4444-555555555555")
U2 = uuid.UUID("22222222-2222-3333-4444-555555555555")
P1 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
P2 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
P3 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")
P4 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000004")


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
async def client(redis_container) -> AsyncIterator[AsyncClient]:
    """Приложение с реальным Redis и подменённым Catalog (фейковый шлюз)."""
    import app.api.cart as cart_module
    from app.application.protocols import ProductStatus
    from app.config import settings
    from app.infrastructure.cart_repository import RedisCartRepository, cart_key
    from app.infrastructure.redis_client import create_client
    from app.main import app

    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(redis_container.port)
    settings.redis_url = f"redis://{host}:{port}"
    original_limit = settings.max_distinct_items
    settings.max_distinct_items = 3

    class AlwaysActiveCatalog:
        calls: ClassVar[list[str]] = []

        async def validate_product(self, product_id: uuid.UUID) -> str:
            self.calls.append(str(product_id))
            return ProductStatus.ACTIVE

    catalog = AlwaysActiveCatalog()
    original_repository = cart_module._repository
    original_catalog = cart_module._catalog
    client = create_client(settings.redis_url)
    repo = RedisCartRepository(client)
    cart_module._repository = lambda: repo
    cart_module._catalog = lambda: catalog

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    cart_module._repository = original_repository
    cart_module._catalog = original_catalog
    settings.max_distinct_items = original_limit
    await client.delete(cart_key(U1))
    await client.delete(cart_key(U2))
    await client.aclose()


HEADERS_U1 = {"X-User-ID": str(U1)}
HEADERS_U2 = {"X-User-ID": str(U2)}


async def test_full_lifecycle(client: AsyncClient):
    """add → get → patch → remove → clear с ожидаемыми статусами."""
    # add (201)
    response = await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P1), "quantity": 2},
        headers=HEADERS_U1,
    )
    assert response.status_code == 201
    assert response.json()["items"][0]["quantity"] == 2
    assert response.json()["items"][0]["added_at"]

    # get (200)
    response = await client.get("/api/v1/cart", headers=HEADERS_U1)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1

    # patch (200)
    response = await client.patch(
        f"/api/v1/cart/items/{P1}", json={"quantity": 5}, headers=HEADERS_U1
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["quantity"] == 5

    # remove (204)
    response = await client.delete(f"/api/v1/cart/items/{P1}", headers=HEADERS_U1)
    assert response.status_code == 204

    # clear (204)
    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P2), "quantity": 1},
        headers=HEADERS_U1,
    )
    response = await client.delete("/api/v1/cart", headers=HEADERS_U1)
    assert response.status_code == 204
    assert (await client.get("/api/v1/cart", headers=HEADERS_U1)).json()["items"] == []


async def test_idempotent_add_same_product(client: AsyncClient):
    """Тот же product_id дважды с quantity 1 -> одна строка с quantity 2."""
    for _ in range(2):
        response = await client.post(
            "/api/v1/cart/items",
            json={"product_id": str(P1), "quantity": 1},
            headers=HEADERS_U1,
        )
        assert response.status_code == 201
    body = await client.get("/api/v1/cart", headers=HEADERS_U1)
    items = body.json()["items"]
    assert len(items) == 1
    assert items[0]["quantity"] == 2


async def test_read_nonexistent_cart_returns_empty_200(client: AsyncClient):
    response = await client.get("/api/v1/cart", headers=HEADERS_U2)
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_missing_item_patch_delete_404(client: AsyncClient):
    patch_response = await client.patch(
        f"/api/v1/cart/items/{P1}", json={"quantity": 1}, headers=HEADERS_U1
    )
    assert patch_response.status_code == 404
    assert patch_response.json()["error"]["code"] == "CART_ITEM_NOT_FOUND"
    assert patch_response.json()["request_id"]
    delete_response = await client.delete(
        f"/api/v1/cart/items/{P1}", headers=HEADERS_U1
    )
    assert delete_response.status_code == 404
    assert delete_response.json()["error"]["code"] == "CART_ITEM_NOT_FOUND"


async def test_max_items_conflict_409_cart_unchanged(client: AsyncClient):
    for pid in (P1, P2, P3):
        response = await client.post(
            "/api/v1/cart/items",
            json={"product_id": str(pid), "quantity": 1},
            headers=HEADERS_U1,
        )
        assert response.status_code == 201
    response = await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P4), "quantity": 1},
        headers=HEADERS_U1,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CART_ITEM_LIMIT"
    cart = (await client.get("/api/v1/cart", headers=HEADERS_U1)).json()
    assert sorted(i["product_id"] for i in cart["items"]) == sorted(
        str(pid) for pid in (P1, P2, P3)
    )


async def test_quantity_bounds_422_cart_unchanged(client: AsyncClient):
    for quantity in (0, -1, 101):
        response = await client.post(
            "/api/v1/cart/items",
            json={"product_id": str(P1), "quantity": quantity},
            headers=HEADERS_U1,
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert (await client.get("/api/v1/cart", headers=HEADERS_U1)).json()["items"] == []

    # PATCH сверх максимума тоже 422, корзина не меняется
    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P1), "quantity": 1},
        headers=HEADERS_U1,
    )
    response = await client.patch(
        f"/api/v1/cart/items/{P1}", json={"quantity": 101}, headers=HEADERS_U1
    )
    assert response.status_code == 422
    cart = (await client.get("/api/v1/cart", headers=HEADERS_U1)).json()
    assert cart["items"][0]["quantity"] == 1


async def test_missing_user_header_401_no_state_created(client: AsyncClient):
    response = await client.get("/api/v1/cart")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MISSING_USER_CONTEXT"

    response = await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P1), "quantity": 1},
        headers={"X-User-ID": "not-a-uuid"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_USER_CONTEXT"


async def test_user_isolation(client: AsyncClient):
    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P1), "quantity": 1},
        headers=HEADERS_U1,
    )
    other = (await client.get("/api/v1/cart", headers=HEADERS_U2)).json()
    assert other["items"] == []
    # U2 не может мутировать корзину U1: PATCH отсутствующего у U2 -> 404
    response = await client.patch(
        f"/api/v1/cart/items/{P1}", json={"quantity": 3}, headers=HEADERS_U2
    )
    assert response.status_code == 404
    mine = (await client.get("/api/v1/cart", headers=HEADERS_U1)).json()
    assert mine["items"][0]["quantity"] == 1


async def test_ttl_expiry_returns_empty_cart(client: AsyncClient):
    """Выселение по TTL: после истечения ключа чтение — пустая корзина."""
    import asyncio

    from app.config import settings

    original_ttl = settings.cart_ttl_seconds
    try:
        await client.post(
            "/api/v1/cart/items",
            json={"product_id": str(P1), "quantity": 1},
            headers=HEADERS_U1,
        )
        settings.cart_ttl_seconds = 1
        # перезаписываем ключ с коротким TTL через PATCH
        response = await client.patch(
            f"/api/v1/cart/items/{P1}", json={"quantity": 1}, headers=HEADERS_U1
        )
        assert response.status_code == 200
        await asyncio.sleep(2)
        cart = (await client.get("/api/v1/cart", headers=HEADERS_U1)).json()
        assert cart["items"] == []
    finally:
        settings.cart_ttl_seconds = original_ttl
