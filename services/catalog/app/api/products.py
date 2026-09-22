"""HTTP-эндпоинты продуктов.

Маршруты: создание (201), список с пагинацией и сортировкой (200),
получение по id (200/404), обновление (200/404/409/422), удаление (204/404).

.. important::

   ``GET /api/v1/products/search`` объявлен **в другом роутере**
   (``app.api.search``) и регистрируется **раньше** ``/{product_id}``
   через ``app.main.include_router``, чтобы FastAPI не матчил
   ``/products/search`` в ``/{product_id}``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.catalog import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.services.products import ProductsService

router = APIRouter(prefix="/api/v1", tags=["products"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def _clamp_limit(limit: int) -> int:
    """Ограничивает ``limit`` диапазоном ``[1, _MAX_LIMIT]``."""
    return max(1, min(limit, _MAX_LIMIT))


@router.post(
    "/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED
)
async def create_product(
    payload: ProductCreate, db: AsyncSession = Depends(get_db)
) -> ProductResponse:
    """Создаёт продукт (``201``); невалидная категория -> ``422``, дубль SKU -> ``409``."""
    return await ProductsService(db).create(payload)


@router.get("/products", response_model=ProductListResponse)
async def list_products(
    category_id: uuid.UUID | None = None,
    is_active: bool = Query(default=True, description="Фильтр по активности"),
    sort: str = Query(default="created_at", description="Поле сортировки"),
    order: str = Query(default="desc", description="Направление сортировки (asc/desc)"),
    offset: int = Query(default=0, ge=0, description="Смещение"),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, description="Размер страницы"),
    db: AsyncSession = Depends(get_db),
) -> ProductListResponse:
    """Возвращает страницу продуктов с общим ``total``.

    ``is_active`` по умолчанию ``true`` (неактивные исключены из listing;
    для просмотра по id используйте ``GET /products/{id}``).
    """
    svc = ProductsService(db)
    products, total = await svc.list(
        category_id=category_id,
        is_active=is_active,
        sort=sort,
        order=order,
        offset=offset,
        limit=_clamp_limit(limit),
    )
    return ProductListResponse(
        items=products, total=total, offset=offset, limit=_clamp_limit(limit)
    )


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ProductResponse:
    """Возвращает продукт по id (``200``) или ``404 PRODUCT_NOT_FOUND``.

    Чтение через Redis read-through кэш (D11); при недоступности Redis —
    деградация на PostgreSQL. Неактивные продукты доступны по прямому id.
    """
    payload = await ProductsService(db).get_product(product_id)
    return ProductResponse.model_validate(payload)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID, payload: ProductUpdate, db: AsyncSession = Depends(get_db)
) -> ProductResponse:
    """Обновляет продукт; ``(404)``, ``(409)`` дубль SKU, ``(422)`` невалидная категория."""
    return await ProductsService(db).update(product_id, payload)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    """Удаляет продукт (``204``); ``(404)`` если не найден."""
    await ProductsService(db).delete(product_id)
