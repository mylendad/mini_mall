"""HTTP-эндпоинты доступности (только чтение).

Маршруты: точечная проверка по SKU (``GET /availability/{sku}``) и пакетная
(``POST /availability/check``, размер списка ограничен — сверх лимита ``422``).
Эндпоинты не изменяют состояние.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas.inventory import (
    AvailabilityBatchRequest,
    AvailabilityBatchResponse,
    AvailabilityResponse,
)
from app.services.availability import AvailabilityService

router = APIRouter(prefix="/availability", tags=["availability"])


@router.get("/{sku}", response_model=AvailabilityResponse)
async def check_availability(
    sku: str, db: AsyncSession = Depends(get_db)
) -> AvailabilityResponse:
    """Возвращает доступность SKU (``200``) или ``404 STOCK_ITEM_NOT_FOUND``."""
    return await AvailabilityService(db).check(sku)


@router.post("/check", response_model=AvailabilityBatchResponse)
async def check_availability_batch(
    payload: AvailabilityBatchRequest, db: AsyncSession = Depends(get_db)
) -> AvailabilityBatchResponse:
    """Пакетная проверка доступности; по элементу на каждый SKU.

    Список SKU больше ``availability_batch_max_skus`` -> ``422``.
    """
    if len(payload.skus) > settings.availability_batch_max_skus:
        from common.errors import ErrorCode, error_detail
        from fastapi import HTTPException

        raise HTTPException(
            status_code=ErrorCode.VALIDATION_ERROR.status_code,
            detail=error_detail(
                ErrorCode.VALIDATION_ERROR,
                f"Batch size exceeds limit of {settings.availability_batch_max_skus} SKUs",
            ),
        )
    items = await AvailabilityService(db).check_batch(payload.skus)
    return AvailabilityBatchResponse(items=items)
