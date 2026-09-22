"""Репозиторий доступа к данным ``categories``.

Описывает операции с моделью :class:`~app.models.catalog.Category` через
переданную асинхронную сессию; транзакционные границы (commit) управляются
сервисным слоем.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.catalog import Category


class CategoryRepository:
    """Работа с моделью :class:`Category`.

    Параметры:
        db: Асинхронная сессия SQLAlchemy (обычно из ``Depends(get_db)``).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, category_id: uuid.UUID) -> Category | None:
        """Возвращает категорию по UUID или ``None``."""
        result = await self.db.execute(
            select(Category).where(Category.id == category_id)
        )
        return result.scalars().first()

    async def get_by_name(self, name: str) -> Category | None:
        """Возвращает категорию по имени или ``None``."""
        result = await self.db.execute(select(Category).where(Category.name == name))
        return result.scalars().first()

    async def list_ordered(self) -> list[Category]:
        """Возвращает все категории, упорядоченные по имени."""
        result = await self.db.execute(select(Category).order_by(Category.name.asc()))
        return list(result.scalars().all())

    async def create(self, name: str, description: str | None) -> Category:
        """Создаёт категорию и делает ``flush`` (без commit)."""
        category = Category(name=name, description=description)
        self.db.add(category)
        await self.db.flush()
        await self.db.refresh(category)
        return category

    async def update(
        self,
        category: Category,
        name: str | None = None,
        description: str | None = None,
    ) -> Category:
        """Обновляет поля категории и делает ``flush`` (без commit)."""
        if name is not None:
            category.name = name
        if description is not None:
            category.description = description
        await self.db.flush()
        await self.db.refresh(category)
        return category

    async def delete(self, category: Category) -> None:
        """Удаляет категорию и делает ``flush`` (без commit).

        При существующих продуктах БД выбросит ``IntegrityError`` из-за
        ``ON DELETE RESTRICT``; транзакция остаётся откатываемой.
        """
        await self.db.delete(category)
        await self.db.flush()
