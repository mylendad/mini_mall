"""Redis недоступен -> контролируемый 503 в стандартном конверте (спека).

Симуляция отказа: репозиторий подключён к недостижимому Redis (порт без
прослушивателя с нулевыми таймаутами). GET и PATCH возвращают 503
``CART_STORAGE_UNAVAILABLE``; сырые исключения наружу не уте­кают.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.api_integration

U1 = uuid.UUID("11111111-2222-3333-4444-555555555555")
P1 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
HEADERS = {"X-User-ID": str(U1)}


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Приложение с репозиторием, подключённым к «мёртвому» Redis."""
    import redis.asyncio as aioredis

    import app.api.cart as cart_module
    from app.config import settings
    from app.infrastructure.cart_repository import RedisCartRepository
    from app.main import app

    dead = aioredis.Redis.from_url(
        "redis://127.0.0.1:1/0",  # порт 1 — соединение отказано мгновенно
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    original_repository = cart_module._repository
    cart_module._repository = lambda: RedisCartRepository(dead)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    cart_module._repository = original_repository
    settings.redis_url = settings.redis_url  # без изменений
    await dead.aclose()


async def test_read_while_redis_down_503(client: AsyncClient):
    response = await client.get("/api/v1/cart", headers=HEADERS)
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "CART_STORAGE_UNAVAILABLE"
    assert "redis" not in body["error"]["message"].lower()
    assert body["request_id"]


async def test_patch_while_redis_down_503(client: AsyncClient):
    response = await client.patch(
        f"/api/v1/cart/items/{P1}", json={"quantity": 2}, headers=HEADERS
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CART_STORAGE_UNAVAILABLE"
