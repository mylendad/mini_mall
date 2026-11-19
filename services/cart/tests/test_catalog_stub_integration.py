"""Интеграционные тесты API с реальным Redis и HTTP-стабом Catalog (5.3).

Проверяется fail-closed семантика добавления (D4): Catalog недоступен ->
503 и корзина без изменений; несуществующий продукт -> 404; неактивный ->
422. GET/PATCH/DELETE работают без Catalog вообще (fail-open).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.infrastructure.breaker import CircuitBreaker
from app.infrastructure.catalog_client import CatalogClient
from tests.stubs import StubCatalogServer, StubResponse

pytestmark = pytest.mark.api_integration

U1 = uuid.UUID("11111111-2222-3333-4444-555555555555")
P1 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
P2 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
P3 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")

HEADERS = {"X-User-ID": str(U1)}


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


class StubGateway:
    """Gateway над стаб-сервером с изолированным breaker."""

    def __init__(self, client: AsyncClient, breaker: CircuitBreaker) -> None:
        self._gateway = CatalogClient(client, breaker=breaker)

    async def validate_product(self, product_id: uuid.UUID) -> str:
        return await self._gateway.validate_product(product_id)


@pytest.fixture
async def setup(redis_container) -> AsyncIterator[dict]:
    """Приложение + стаб Catalog (по умолчанию все продукты активны)."""
    import app.api.cart as cart_module
    from app.config import settings
    from app.infrastructure.cart_repository import RedisCartRepository, cart_key
    from app.infrastructure.redis_client import create_client
    from app.main import app

    behavior: dict = {"status": 200, "is_active": True}

    async def handler(path: str) -> StubResponse:
        return StubResponse(
            status=behavior["status"], body=b'{"is_active": %s}' % str(behavior["is_active"]).lower().encode()
        )

    server = StubCatalogServer(handler)
    await server.start()

    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(redis_container.port)
    settings.redis_url = f"redis://{host}:{port}"

    original_base = settings.catalog_base_url
    settings.catalog_base_url = server.base_url

    from app.infrastructure.catalog_http import (
        get_catalog_http_client,
    )
    from app.infrastructure.catalog_http import (
        init as init_catalog_http,
    )

    init_catalog_http()  # клиент базой на стаб

    redis_client = create_client(settings.redis_url)
    repo = RedisCartRepository(redis_client)
    gateway = StubGateway(
        get_catalog_http_client(),
        CircuitBreaker(failure_threshold=3, open_seconds=30.0),
    )

    original_repository = cart_module._repository
    original_catalog = cart_module._catalog
    cart_module._repository = lambda: repo
    cart_module._catalog = lambda: gateway

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield {"client": ac, "server": server, "behavior": behavior}

    cart_module._repository = original_repository
    cart_module._catalog = original_catalog
    settings.catalog_base_url = original_base
    await redis_client.delete(cart_key(U1))
    await redis_client.aclose()
    await server.stop()


async def test_catalog_down_during_add_503_cart_unchanged(setup):
    """Стаб не отвечает на соединение (закрыт) -> 503, корзина не меняется."""
    client = setup["client"]
    behavior = setup["behavior"]

    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P1), "quantity": 1},
        headers=HEADERS,
    )
    behavior["status"] = 503  # недоступность

    response = await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P2), "quantity": 1},
        headers=HEADERS,
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CATALOG_UNAVAILABLE"
    cart = (await client.get("/api/v1/cart", headers=HEADERS)).json()
    assert [i["product_id"] for i in cart["items"]] == [str(P1)]


async def test_nonexistent_product_404_cart_unchanged(setup):
    client = setup["client"]
    behavior = setup["behavior"]

    behavior["status"] = 404
    response = await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P2), "quantity": 1},
        headers=HEADERS,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"
    cart = (await client.get("/api/v1/cart", headers=HEADERS)).json()
    assert cart["items"] == []


async def test_inactive_product_422_cart_unchanged(setup):
    client = setup["client"]
    behavior = setup["behavior"]

    behavior["is_active"] = False
    response = await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P2), "quantity": 1},
        headers=HEADERS,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PRODUCT_INACTIVE"
    cart = (await client.get("/api/v1/cart", headers=HEADERS)).json()
    assert cart["items"] == []


async def test_operations_without_catalog(setup):
    """GET/PATCH/DELETE не зависят от Catalog даже когда он отдаёт 500."""
    client = setup["client"]
    behavior = setup["behavior"]

    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P1), "quantity": 2},
        headers=HEADERS,
    )
    behavior["status"] = 500  # недоступен, но читается/мутируется иначе нельзя

    get_response = await client.get("/api/v1/cart", headers=HEADERS)
    assert get_response.status_code == 200

    patch_response = await client.patch(
        f"/api/v1/cart/items/{P1}", json={"quantity": 3}, headers=HEADERS
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["items"][0]["quantity"] == 3

    delete_response = await client.delete(f"/api/v1/cart/items/{P1}", headers=HEADERS)
    assert delete_response.status_code == 204
