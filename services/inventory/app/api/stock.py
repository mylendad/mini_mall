"""HTTP-эндпоинты склада (админский учёт).

Маршруты: создание позиции (201), список с пагинацией (200), получение
по id/SKU (200/404), обновление порога low-stock (200/404), корректировка
количества (200/404/422). ``GET /stock-items/by-sku/{sku}`` регистрируется
раньше ``GET /stock-items/{item_id}`` (порядок в ``app.main``).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas.inventory import (
    StockItemAdjust,
    StockItemCreate,
    StockItemListResponse,
    StockItemResponse,
    StockItemThresholdUpdate,
)
from app.services.stock import StockService

router = APIRouter(prefix="/stock-items", tags=["stock"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def _clamp_limit(limit: int) -> int:
    """Ограничивает ``limit`` диапазоном ``[1, _MAX_LIMIT]``."""
    return max(1, min(limit, _MAX_LIMIT))


@router.post("", response_model=StockItemResponse, status_code=201)
async def create_stock_item(
    payload: StockItemCreate, db: AsyncSession = Depends(get_db)
) -> StockItemResponse:
    """Создаёт складскую позицию (``201``); дубль SKU -> ``409``."""
    item = await StockService(db).create(payload)
    return StockItemResponse.model_validate(item)


@router.get("", response_model=StockItemListResponse)
async def list_stock_items(
    offset: int = Query(default=0, ge=0, description="Смещение"),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, description="Размер страницы"),
    db: AsyncSession = Depends(get_db),
) -> StockItemListResponse:
    """Возвращает страницу складских позиций с общим ``total``."""
    items, total = await StockService(db).list(
        offset=offset, limit=_clamp_limit(limit)
    )
    return StockItemListResponse(
        items=[StockItemResponse.model_validate(i) for i in items],
        total=total,
        offset=offset,
        limit=_clamp_limit(limit),
    )


@router.get("/by-sku/{sku}", response_model=StockItemResponse)
async def get_stock_item_by_sku(
    sku: str, db: AsyncSession = Depends(get_db)
) -> StockItemResponse:
    """Возвращает позицию по SKU (``200``) или ``404 STOCK_ITEM_NOT_FOUND``."""
    item = await StockService(db).get_by_sku(sku)
    return StockItemResponse.model_validate(item)


@router.get("/{item_id}", response_model=StockItemResponse)
async def get_stock_item(
    item_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> StockItemResponse:
    """Возвращает позицию по id (``200``) или ``404 STOCK_ITEM_NOT_FOUND``."""
    item = await StockService(db).get_by_id(item_id)
    return StockItemResponse.model_validate(item)


@router.patch("/{item_id}", response_model=StockItemResponse)
async def update_stock_item_threshold(
    item_id: uuid.UUID,
    payload: StockItemThresholdUpdate,
    db: AsyncSession = Depends(get_db),
) -> StockItemResponse:
    """Обновляет порог low-stock (``200``); ``(404)`` если не найдена."""
    item = await StockService(db).update_threshold(
        item_id, payload.low_stock_threshold
    )
    return StockItemResponse.model_validate(item)


@router.post("/{item_id}/adjustments", response_model=StockItemResponse)
async def adjust_stock_item(
    item_id: uuid.UUID,
    payload: StockItemAdjust,
    db: AsyncSession = Depends(get_db),
) -> StockItemResponse:
    """Корректирует количество (``200``); ``(404)``, ``(422)`` ниже нуля."""
    item = await StockService(db).adjust(
        item_id, payload.delta, payload.reason
    )
    return StockItemResponse.model_validate(item)


def default_ttl() -> int:
    """TTL резерва по умолчанию из настроек (используется роутером резервов)."""
    return settings.reservation_default_ttl_seconds
