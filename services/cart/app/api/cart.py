"""HTTP-эндпоинты корзины (задачи 4.1/4.3).

Маршруты под ``/api/v1`` (plural-free, по спеке):
    - ``GET /cart`` — 200 (отсутствующая корзина -> пустая);
    - ``POST /cart/items`` — 201 (Catalog валидирует продукт только здесь, D4);
    - ``PATCH /cart/items/{product_id}`` — 200 / 404;
    - ``DELETE /cart/items/{product_id}`` — 204 / 404;
    - ``DELETE /cart`` — 204 (очистка; 204 — исключение из «мутация возвращает
      состояние корзины», допустимое по спеке).

Ошибки use cases маппятся в стандартный конверт через ``app.errors``;
сырые исключения Redis/HTTP клиенту не видны.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_user_id
from app.api.schemas import (
    AddItemRequest,
    CartResponse,
    UpdateItemRequest,
)
from app.application.protocols import (
    CatalogUnavailable,
    ProductInactive,
    ProductNotFound,
)
from app.application.use_cases import CartUseCases
from app.errors import map_exception
from app.infrastructure.catalog_client import CatalogClient
from app.infrastructure.catalog_http import get_catalog_http_client
from app.infrastructure.redis_client import get_client
from app.metrics import (
    cart_items_added_total,
    cart_items_removed_total,
    cart_validation_rejected_total,
)

router = APIRouter(prefix="/api/v1", tags=["cart"])


def _repository():
    from app.infrastructure.cart_repository import RedisCartRepository

    return RedisCartRepository(get_client())


def _use_cases() -> CartUseCases:
    return CartUseCases(_repository())


def _catalog() -> CatalogClient:
    return CatalogClient(get_catalog_http_client())


def _raise_mapped(exc: Exception) -> None:
    """Маппит исключение use case в HTTPException стандартного конверта."""
    mapped = map_exception(exc)
    if mapped is not None:
        raise HTTPException(status_code=mapped[0], detail=mapped[1]) from exc
    raise exc


@router.get("/cart", response_model=CartResponse)
async def get_cart(user_id: UUID = Depends(get_user_id)) -> CartResponse:
    """Возвращает корзину пользователя (отсутствующая -> пустая)."""
    try:
        cart = await _use_cases().get_cart(user_id)
    except Exception as exc:  # noqa: BLE001 - маппинг знает конкретные типы
        _raise_mapped(exc)
    return CartResponse(user_id=cart.user_id, items=cart.items.values())  # type: ignore[arg-type]


@router.post(
    "/cart/items",
    response_model=CartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    payload: AddItemRequest, user_id: UUID = Depends(get_user_id)
) -> CartResponse:
    """Добавляет товар (повторное добавление увеличивает количество).

    Catalog валидирует продукт (404/422/503); лимит -> 409; границы -> 422.
    """
    try:
        cart = await _use_cases().add_item(
            user_id, payload.product_id, payload.quantity, catalog=_catalog()
        )
    except Exception as exc:  # noqa: BLE001 - маппинг знает конкретные типы
        if isinstance(exc, ProductNotFound):
            cart_validation_rejected_total.labels(reason="product_not_found").inc()
        elif isinstance(exc, ProductInactive):
            cart_validation_rejected_total.labels(reason="product_inactive").inc()
        elif isinstance(exc, CatalogUnavailable):
            cart_validation_rejected_total.labels(reason="catalog_unavailable").inc()
        _raise_mapped(exc)
    cart_items_added_total.inc()
    return CartResponse(user_id=cart.user_id, items=cart.items.values())  # type: ignore[arg-type]


@router.patch("/cart/items/{product_id}", response_model=CartResponse)
async def update_item(
    product_id: UUID,
    payload: UpdateItemRequest,
    user_id: UUID = Depends(get_user_id),
) -> CartResponse:
    """Задаёт абсолютное количество товара; отсутствие -> 404."""
    try:
        cart = await _use_cases().set_quantity(user_id, product_id, payload.quantity)
    except Exception as exc:  # noqa: BLE001 - маппинг знает конкретные типы
        _raise_mapped(exc)
    return CartResponse(user_id=cart.user_id, items=cart.items.values())  # type: ignore[arg-type]


@router.delete("/cart/items/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(
    product_id: UUID, user_id: UUID = Depends(get_user_id)
) -> None:
    """Удаляет товар; отсутствие -> 404."""
    try:
        await _use_cases().remove_item(user_id, product_id)
    except Exception as exc:  # noqa: BLE001 - маппинг знает конкретные типы
        _raise_mapped(exc)
    cart_items_removed_total.inc()


@router.delete("/cart", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(user_id: UUID = Depends(get_user_id)) -> None:
    """Полностью очищает корзину."""
    try:
        await _use_cases().clear_cart(user_id)
    except Exception as exc:  # noqa: BLE001 - маппинг знает конкретные типы
        _raise_mapped(exc)
