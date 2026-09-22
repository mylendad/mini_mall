"""Репозиторий доступа к данным ``products``.

Фильтрация, сортировка и пагинация выполняются на стороне БД (SQL), без
загрузки всего каталога в память. Коммит — во владении сервисного слоя.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product

SORT_COLUMNS = {
    "created_at": Product.created_at,
    "updated_at": Product.updated_at,
    "name": Product.name,
    "price": Product.price,
}


class ProductRepository:
    """Работа с моделью :class:`Product`.

    Параметры:
        db: Асинхронная сессия SQLAlchemy (обычно из ``Depends(get_db)``).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        """Возвращает продукт по UUID или ``None``."""
        result = await self.db.execute(select(Product).where(Product.id == product_id))
        return result.scalars().first()

    async def get_by_sku(self, sku: str) -> Product | None:
        """Возвращает продукт по SKU или ``None``."""
        result = await self.db.execute(select(Product).where(Product.sku == sku))
        return result.scalars().first()

    async def list(
        self,
        *,
        category_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        sort: str = "created_at",
        order: str = "desc",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Product], int]:
        """Возвращает ``(страница продуктов, всего совпадений)``.

        Параметры:
            category_id: Фильтр по категории.
            is_active: Фильтр по активности.
            sort: Ключ сортировки из ``SORT_COLUMNS`` (иначе ``ValueError``).
            order: ``asc`` или ``desc``.
            offset: Смещение страницы.
            limit: Размер страницы.

        Исключения:
            ValueError: неизвестный ``sort``.
        """
        if sort not in SORT_COLUMNS:
            raise ValueError(f"unsupported sort key: {sort}")
        if order not in ("asc", "desc"):
            raise ValueError(f"unsupported order: {order}")

        where = []
        if category_id is not None:
            where.append(Product.category_id == category_id)
        if is_active is not None:
            where.append(Product.is_active == is_active)

        total_result = await self.db.execute(
            select(func.count()).select_from(Product).where(*where)
        )
        total = total_result.scalar_one()

        order_column = SORT_COLUMNS[sort]
        order_expr = order_column.desc() if order == "desc" else order_column.asc()
        rows_result = await self.db.execute(
            select(Product)
            .where(*where)
            .order_by(order_expr)
            .offset(offset)
            .limit(limit)
        )
        return list(rows_result.scalars().all()), total

    async def create(
        self,
        *,
        category_id: uuid.UUID,
        name: str,
        description: str | None,
        price: Decimal,
        currency: str,
        sku: str,
        attributes: dict,
        is_active: bool = True,
        created_at: datetime | None = None,
    ) -> Product:
        """Создаёт продукт и делает ``flush`` (без commit)."""
        product = Product(
            category_id=category_id,
            name=name,
            description=description,
            price=price,
            currency=currency,
            sku=sku,
            attributes=attributes,
            is_active=is_active,
            created_at=created_at or datetime.now(UTC),
        )
        self.db.add(product)
        await self.db.flush()
        await self.db.refresh(product)
        return product

    async def update(self, product: Product, **fields) -> Product:
        """Обновляет переданные поля продукта и делает ``flush`` (без commit)."""
        for key, value in fields.items():
            if value is not None:
                setattr(product, key, value)
        await self.db.flush()
        await self.db.refresh(product)
        return product

    async def delete(self, product: Product) -> None:
        """Удаляет продукт и делает ``flush`` (без commit)."""
        await self.db.delete(product)
        await self.db.flush()
