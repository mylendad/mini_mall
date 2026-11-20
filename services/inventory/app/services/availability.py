"""Сервис доступности: только чтение, без побочных эффектов.

Отвечает по SKU: ``quantity_on_hand``, ``quantity_reserved``,
производные ``available`` и ``in_stock``. Никаких записей и коммитов —
эндпоинты доступности не изменяют состояние (спека).
"""

from __future__ import annotations

from common.errors import ErrorCode, error_detail
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.stock_repo import StockRepository
from app.schemas.inventory import (
    AvailabilityBatchItem,
    AvailabilityResponse,
)


class AvailabilityService:
    """Точечные и пакетные проверки доступности.

    Параметры:
        db: Асинхронная сессия SQLAlchemy.
    """

    def __init__(self, db: AsyncSession):
        self.repo = StockRepository(db)

    async def check(self, sku: str) -> AvailabilityResponse:
        """Возвращает доступность SKU или ``404 STOCK_ITEM_NOT_FOUND``."""
        row = await self.repo.get_availability_by_sku(sku)
        if row is None:
            raise HTTPException(
                status_code=ErrorCode.STOCK_ITEM_NOT_FOUND.status_code,
                detail=error_detail(ErrorCode.STOCK_ITEM_NOT_FOUND),
            )
        on_hand, reserved = row
        return AvailabilityResponse.build(sku=sku, on_hand=on_hand, reserved=reserved)

    async def check_batch(self, skus: list[str]) -> list[AvailabilityBatchItem]:
        """Возвращает по элементу на каждый SKU; неизвестные SKU — ``found=False``.

        Пакет не «падает» из-за одного неизвестного SKU.
        """
        found = await self.repo.get_availability_batch(skus)
        items = []
        for sku in skus:
            row = found.get(sku)
            if row is None:
                items.append(AvailabilityBatchItem(sku=sku, found=False))
                continue
            on_hand, reserved = row
            available = on_hand - reserved
            items.append(
                AvailabilityBatchItem(
                    sku=sku,
                    found=True,
                    quantity_on_hand=on_hand,
                    quantity_reserved=reserved,
                    available=available,
                    in_stock=available > 0,
                )
            )
        return items
