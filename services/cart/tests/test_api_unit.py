"""Юнит-тесты зависимости ``X-User-ID`` (задача 4.2).

Проверяются: отсутствующий заголовок (401 MISSING_USER_CONTEXT), не-UUID
(401 INVALID_USER_CONTEXT), валидный UUID (200) и 404/409-сценарии на
приложении с фейковым репозиторием (задача 4.3).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_user_id
from tests.test_use_cases import FakeCartRepository

U1 = uuid.UUID("11111111-2222-3333-4444-555555555555")
P1 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


@pytest.fixture
def app() -> Iterator[FastAPI]:
    """Приложение create_app с фейковым репозиторием (без Redis и Catalog).

    Используется реальный ``create_app`` (обработчики ошибок в конверте
    ``ErrorResponse``), но Redis и Catalog подменяются фейками.
    """
    from app.config import settings
    from app.main import create_app

    app = create_app()

    repo = FakeCartRepository()

    original_max = settings.max_quantity
    settings.max_quantity = 10

    # get_user_id не подменяется: он не ходит в Redis/Catalog, поэтому
    # 401 на отсутствующий/битый заголовок проверяется здесь же.
    # Подмена внутреннего провайдера use cases на фейковый репозиторий.
    import app.api.cart as cart_module

    original_repository = cart_module._repository
    cart_module._repository = lambda: repo
    original_catalog = cart_module._catalog
    cart_module._catalog = lambda: None  # не используется: use case без шлюза

    yield app

    settings.max_quantity = original_max
    app.dependency_overrides.clear()
    cart_module._repository = original_repository
    cart_module._catalog = original_catalog


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def test_user_id_dependency_missing_header():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        await get_user_id(None)
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail["code"] == "MISSING_USER_CONTEXT"


async def test_user_id_dependency_invalid_uuid():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        await get_user_id("not-a-uuid")
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail["code"] == "INVALID_USER_CONTEXT"


async def test_user_id_dependency_happy_path():
    result = await get_user_id(str(U1))
    assert result == U1


async def test_get_empty_cart_returns_200(client: AsyncClient):
    response = await client.get("/api/v1/cart", headers={"X-User-ID": str(U1)})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(U1)
    assert body["items"] == []


async def test_patch_missing_item_returns_404_envelope(client: AsyncClient):
    response = await client.patch(
        f"/api/v1/cart/items/{P1}", json={"quantity": 1}, headers={"X-User-ID": str(U1)}
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "CART_ITEM_NOT_FOUND"
    assert "request_id" in body


async def test_delete_missing_item_returns_404_envelope(client: AsyncClient):
    response = await client.delete(
        f"/api/v1/cart/items/{P1}", headers={"X-User-ID": str(U1)}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CART_ITEM_NOT_FOUND"


async def test_invalid_quantity_rejected_422(client: AsyncClient):
    response = await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(P1), "quantity": 0},
        headers={"X-User-ID": str(U1)},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_invalid_uuid_path_param_rejected_422(client: AsyncClient):
    response = await client.patch(
        "/api/v1/cart/items/not-a-uuid",
        json={"quantity": 1},
        headers={"X-User-ID": str(U1)},
    )
    assert response.status_code == 422


async def test_api_requires_user_header(client: AsyncClient):
    response = await client.get("/api/v1/cart")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MISSING_USER_CONTEXT"
