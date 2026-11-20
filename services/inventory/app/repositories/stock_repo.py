"""Репозиторий доступа к данным ``stock_items``.

Фильтрация и пагинация выполняются на стороне БД (SQL). Коммит — во
владении сервисного слоя. Корректировки выполняются атомарным условным
UPDATE: уменьшение, приводящее ``quantity_on_hand`` к отрицательному
значению, отклоняется (0 строк совпало), а не вызывает ошибку на уровне
приложения.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import StockItem


class StockRepository:
    """Работа с моделью :class:`StockItem`.

    Параметры:
        db: Асинхронная сессия SQLAlchemy (обычно из ``Depends(get_db)``).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, item_id: uuid.UUID) -> StockItem | None:
        """Возвращает позицию по UUID или ``None``."""
        result = await self.db.execute(
            select(StockItem).where(StockItem.id == item_id)
        )
        return result.scalars().first()

    async def get_by_sku(self, sku: str) -> StockItem | None:
        """Возвращает позицию по SKU или ``None``."""
        result = await self.db.execute(select(StockItem).where(StockItem.sku == sku))
        return result.scalars().first()

    async def list(
        self, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[StockItem], int]:
        """Возвращает ``(страница позиций, всего)`` (пагинация на стороне БД)."""
        total = (
            await self.db.execute(select(func.count()).select_from(StockItem))
        ).scalar_one()
        rows = await self.db.execute(
            select(StockItem).order_by(StockItem.created_at).offset(offset).limit(limit)
        )
        return list(rows.scalars().all()), total

    async def create(
        self,
        *,
        sku: str,
        quantity_on_hand: int = 0,
        low_stock_threshold: int = 0,
        catalog_product_id: uuid.UUID | None = None,
    ) -> StockItem:
        """Создаёт позицию и делает ``flush`` (без commit).

        Уникальность SKU защищена ограничением БД; конкурентный дубль
        отображается маппером ошибок из ``IntegrityError``.
        """
        item = StockItem(
            sku=sku,
            quantity_on_hand=quantity_on_hand,
            quantity_reserved=0,
            low_stock_threshold=low_stock_threshold,
            catalog_product_id=catalog_product_id,
        )
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def adjust_quantity(self, item: StockItem, delta: int) -> StockItem:
        """Атомарно изменяет ``quantity_on_hand`` на ``delta``.

        Условный UPDATE отклоняет уменьшение ниже нуля (0 строк совпало ->
        ``None``). ``flush`` без commit.
        """
        if delta >= 0:
            result = await self.db.execute(
                update(StockItem)
                .where(StockItem.id == item.id)
                .values(quantity_on_hand=StockItem.quantity_on_hand + delta)
                .returning(StockItem.id)
            )
        else:
            result = await self.db.execute(
                update(StockItem)
                .where(
                    StockItem.id == item.id,
                    StockItem.quantity_on_hand + delta >= 0,
                )
                .values(quantity_on_hand=StockItem.quantity_on_hand + delta)
                .returning(StockItem.id)
            )
        if result.first() is None:
            return None
        await self.db.refresh(item)
        return item

    async def update_threshold(self, item: StockItem, threshold: int) -> StockItem:
        """Обновляет порог low-stock (``flush`` без commit)."""
        await self.db.execute(
            update(StockItem)
            .where(StockItem.id == item.id)
            .values(low_stock_threshold=threshold)
        )
        await self.db.refresh(item)
        return item

    async def get_availability_by_sku(self, sku: str) -> tuple[int, int] | None:
        """Возвращает ``(on_hand, reserved)`` для SKU или ``None`` (только чтение)."""
        item = await self.get_by_sku(sku)
        if item is None:
            return None
        return item.quantity_on_hand, item.quantity_reserved

    async def get_availability_batch(
        self, skus: list[str]
    ) -> dict[str, tuple[int, int]]:
        """Возвращает ``{sku: (on_hand, reserved)}`` только для существующих SKU."""
        rows = await self.db.execute(
            select(StockItem.sku, StockItem.quantity_on_hand, StockItem.quantity_reserved)
            .where(StockItem.sku.in_(skus))
        )
        return {sku: (on_hand, reserved) for sku, on_hand, reserved in rows.all()}
