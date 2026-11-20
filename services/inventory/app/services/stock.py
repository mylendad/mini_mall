"""Сервис складских позиций (транзакционная граница + outbox-события).

После успешной мутации в той же транзакции ставится событие в outbox
(``inventory.stock_item.created``/``inventory.stock.adjusted``/
``inventory.threshold.updated``); при уменьшении доступности ниже порога
low-stock в той же транзакции ставится и ``inventory.low_stock``. Откат
транзакции не оставляет ни изменения, ни события.
"""

from __future__ import annotations

import uuid

from common.errors import ErrorCode, error_detail
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import IntegrityErrorMapper
from app.models.inventory import StockItem
from app.repositories.stock_repo import StockRepository
from app.schemas.inventory import StockItemCreate
from app.services.events import (
    STOCK_ADJUSTED,
    STOCK_ITEM_CREATED,
    THRESHOLD_UPDATED,
    enqueue_event,
    is_low_stock_crossing,
    low_stock_envelope,
    stock_item_envelope,
)


class StockService:
    """Операции со складскими позициями.

    Параметры:
        db: Асинхронная сессия SQLAlchemy.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = StockRepository(db)
        self.mapper = IntegrityErrorMapper()

    async def create(self, payload: StockItemCreate) -> StockItem:
        """Создаёт позицию (``409`` дубль SKU) и ставит ``stock_item.created``."""
        if await self.repo.get_by_sku(payload.sku):
            raise HTTPException(
                status_code=ErrorCode.DUPLICATE_SKU.status_code,
                detail=error_detail(
                    ErrorCode.DUPLICATE_SKU, "Stock item SKU already exists"
                ),
            )
        try:
            item = await self.repo.create(
                sku=payload.sku,
                quantity_on_hand=payload.quantity_on_hand,
                low_stock_threshold=payload.low_stock_threshold,
                catalog_product_id=payload.catalog_product_id,
            )
            await enqueue_event(
                self.db, stock_item_envelope(STOCK_ITEM_CREATED, item)
            )
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            mapped = self.mapper.stock_item_write(exc)
            if mapped is not None:
                raise HTTPException(
                    status_code=ErrorCode(mapped["code"]).status_code,
                    detail=mapped,
                )
            raise
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> StockItem:
        """Возвращает позицию по id или ``404 STOCK_ITEM_NOT_FOUND``."""
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(
                status_code=ErrorCode.STOCK_ITEM_NOT_FOUND.status_code,
                detail=error_detail(ErrorCode.STOCK_ITEM_NOT_FOUND),
            )
        return item

    async def get_by_sku(self, sku: str) -> StockItem:
        """Возвращает позицию по SKU или ``404 STOCK_ITEM_NOT_FOUND``."""
        item = await self.repo.get_by_sku(sku)
        if item is None:
            raise HTTPException(
                status_code=ErrorCode.STOCK_ITEM_NOT_FOUND.status_code,
                detail=error_detail(ErrorCode.STOCK_ITEM_NOT_FOUND),
            )
        return item

    async def list(
        self, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[StockItem], int]:
        """Возвращает ``(страница позиций, всего)``."""
        return await self.repo.list(offset=offset, limit=limit)

    async def adjust(
        self, item_id: uuid.UUID, delta: int, reason: str
    ) -> StockItem:
        """Корректирует ``quantity_on_hand`` на ``delta`` (приёмка/исправление).

        Исключения:
            HTTPException(404): позиция не найдена.
            HTTPException(422): корректировка приводит ``on_hand`` к < 0.
        """
        item = await self.get_by_id(item_id)
        available_before = item.available
        updated = await self.repo.adjust_quantity(item, delta)
        if updated is None:
            await self.db.rollback()
            raise HTTPException(
                status_code=ErrorCode.VALIDATION_ERROR.status_code,
                detail=error_detail(
                    ErrorCode.VALIDATION_ERROR,
                    "Adjustment would make quantity_on_hand negative",
                ),
            )
        await enqueue_event(
            self.db,
            stock_item_envelope(
                STOCK_ADJUSTED, updated, extra={"delta": delta, "reason": reason}
            ),
        )
        if (
            delta < 0
            and is_low_stock_crossing(
                available_before=available_before,
                available_after=updated.available,
                threshold=updated.low_stock_threshold,
            )
        ):
            await enqueue_event(
                self.db,
                low_stock_envelope(
                    updated,
                    available_before=available_before,
                    available_after=updated.available,
                ),
            )
        await self.db.commit()
        return updated

    async def update_threshold(
        self, item_id: uuid.UUID, threshold: int
    ) -> StockItem:
        """Обновляет порог low-stock и ставит ``threshold.updated``."""
        item = await self.get_by_id(item_id)
        updated = await self.repo.update_threshold(item, threshold)
        await enqueue_event(
            self.db, stock_item_envelope(THRESHOLD_UPDATED, updated)
        )
        await self.db.commit()
        return updated
