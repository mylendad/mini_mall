"""HTTP-эндпоинты категорий.

Маршруты регистрируются с префиксом ``/api/v1/categories``: создание (201),
список, получение по id (200/404), обновление (200/404/409) и удаление
(204/404/409). Обработчики остаются тонкими: бизнес-логика и код ошибок —
в :class:`~app.services.categories.CategoriesService`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.catalog import CategoryCreate, CategoryResponse, CategoryUpdate
from app.services.categories import CategoriesService

router = APIRouter(prefix="/api/v1", tags=["categories"])


@router.post(
    "/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED
)
async def create_category(
    payload: CategoryCreate, db: AsyncSession = Depends(get_db)
) -> CategoryResponse:
    """Создаёт категорию (``201``); дубликат имени -> ``409``."""
    return await CategoriesService(db).create(payload)


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db)) -> list[CategoryResponse]:
    """Возвращает категории, отсортированные по имени."""
    return await CategoriesService(db).list()


@router.get("/categories/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> CategoryResponse:
    """Возвращает категорию по id (``200``) или ``404 CATEGORY_NOT_FOUND``."""
    return await CategoriesService(db).get(category_id)


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, db: AsyncSession = Depends(get_db)
) -> CategoryResponse:
    """Обновляет категорию (``200``); переименование в дубликат -> ``409``."""
    return await CategoriesService(db).update(category_id, payload)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    """Удаляет пустую категорию (``204``); с продуктами -> ``409 CATEGORY_HAS_PRODUCTS``."""
    await CategoriesService(db).delete(category_id)
