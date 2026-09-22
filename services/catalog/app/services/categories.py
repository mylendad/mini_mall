"""Сервис категорий.

Владеет транзакционными границами: валидация (дубликат имени, наличие
категории), изменение строки через репозиторий и commit. Обработчики API
остаются тонкими.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import IntegrityErrorMapper, error_detail
from app.models.catalog import Category
from app.repositories.category_repo import CategoryRepository
from app.schemas.catalog import CategoryCreate, CategoryUpdate


class CategoriesService:
    """Операции с категориями.

    Параметры:
        db: Асинхронная сессия SQLAlchemy.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CategoryRepository(db)
        self.mapper = IntegrityErrorMapper()

    async def create(self, payload: CategoryCreate) -> Category:
        """Создаёт категорию; дубликат имени -> ``409 DUPLICATE_CATEGORY``."""
        if await self.repo.get_by_name(payload.name):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "DUPLICATE_CATEGORY", "Category name already exists"
                ),
            )
        try:
            category = await self.repo.create(
                name=payload.name, description=payload.description
            )
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            mapped = self.mapper.category_write(exc)
            if mapped is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=mapped)
            raise
        return category

    async def get(self, category_id: uuid.UUID) -> Category:
        """Возвращает категорию или ``404 CATEGORY_NOT_FOUND``."""
        category = await self.repo.get_by_id(category_id)
        if category is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("CATEGORY_NOT_FOUND", "Category not found"),
            )
        return category

    async def list(self) -> list[Category]:
        """Возвращает категории, отсортированные по имени."""
        return await self.repo.list_ordered()

    async def update(self, category_id: uuid.UUID, payload: CategoryUpdate) -> Category:
        """Обновляет категорию; переименование в дубликат -> ``409``."""
        category = await self.get(category_id)
        if (
            payload.name is not None
            and payload.name != category.name
            and await self.repo.get_by_name(payload.name)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "DUPLICATE_CATEGORY", "Category name already exists"
                ),
            )
        try:
            category = await self.repo.update(
                category, name=payload.name, description=payload.description
            )
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            mapped = self.mapper.category_write(exc)
            if mapped is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=mapped)
            raise
        return category

    async def delete(self, category_id: uuid.UUID) -> None:
        """Удаляет пустую категорию; с продуктами -> ``409 CATEGORY_HAS_PRODUCTS``."""
        category = await self.get(category_id)
        try:
            await self.repo.delete(category)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            mapped = self.mapper.category_delete(exc)
            if mapped is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=mapped)
            raise
