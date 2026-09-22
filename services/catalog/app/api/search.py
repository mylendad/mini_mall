"""HTTP-эндпоинт поиска продуктов.

``GET /api/v1/products/search`` объявлен в отдельном роутере и включается
в приложение **раньше** ``app.api.products`` (``GET /products/{product_id}``),
чтобы FastAPI не матчил ``/products/search`` в параметр ``{product_id}``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Query

from app import elasticsearch as es
from app.schemas.catalog import ProductSearchResponse
from app.services.search import SearchQuery, search_products

router = APIRouter(prefix="/api/v1", tags=["products"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def _clamp_limit(limit: int) -> int:
    """Ограничивает ``limit`` диапазоном ``[1, _MAX_LIMIT]``."""
    return max(1, min(limit, _MAX_LIMIT))


@router.get("/products/search", response_model=ProductSearchResponse)
async def search_products_endpoint(
    q: str = Query(
        default="", description="Полнотекстовый запрос (пустой — match-all)"
    ),
    category_id: uuid.UUID | None = Query(default=None),
    min_price: Decimal | None = Query(default=None),
    max_price: Decimal | None = Query(default=None),
    sort: str = Query(
        default="relevance", description="relevance|price|created_at|name"
    ),
    order: str = Query(default="desc", description="asc|desc"),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, description="Размер страницы"),
    offset: int = Query(default=0, ge=0, description="Смещение"),
) -> ProductSearchResponse:
    """Ищет активные продукты; неактивные исключаются всегда (фильтр в DSL)."""
    params = SearchQuery(
        q=q,
        category_id=category_id,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        order=order,
        limit=_clamp_limit(limit),
        offset=offset,
    )
    items, total, facets = await search_products(es.es_client, params)
    return ProductSearchResponse(
        total=total,
        limit=params.limit,
        offset=params.offset,
        items=items,
        facets=facets,
    )
