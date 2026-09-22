"""Поисковый слой: публичные параметры -> ES-запрос, результат -> DTO.

Весь ES DSL изолирован здесь (единое место построения запроса и маппинга
hits), поэтому из роутеров DSL не просачивается: API-слой получает только
стабильные :class:`ProductSearchResult`. Пустой/пробельный ``q`` трактуется
как match-all с фильтрами. Фильтр ``is_active=true`` добавляется всегда —
неактивные продукты не ищутся (D5/D6).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from common.errors import ErrorDetail
from elasticsearch import AsyncElasticsearch, TransportError
from fastapi import HTTPException, status

from app.elasticsearch import CATALOG_INDEX
from app.metrics import catalog_search_unavailable_total
from app.schemas.catalog import ProductSearchResult
from app.services.breaker import BreakerOpenError, search_breaker

SEARCH_SORTS = ("relevance", "price", "created_at", "name")
SEARCH_ORDERS = ("asc", "desc")
MAX_LIMIT = 100
DEFAULT_LIMIT = 20


class InvalidSortError(ValueError):
    """Неизвестный ключ сортировки или порядок."""


@dataclass
class SearchQuery:
    """Публичные параметры поиска ('' у q означает match-all)."""

    q: str = ""
    category_id: uuid.UUID | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    sort: str = "relevance"
    order: str = "desc"
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        self.q = (self.q or "").strip()
        self.limit = max(1, min(self.limit, MAX_LIMIT))
        if self.sort not in SEARCH_SORTS or self.order not in SEARCH_ORDERS:
            raise InvalidSortError(self.sort)


def build_query(params: SearchQuery) -> dict:
    """Строит тело ES-запроса (DSL не покидает этот модуль)."""
    filters: list[dict] = [{"term": {"is_active": True}}]
    if params.category_id is not None:
        filters.append({"term": {"category_id": str(params.category_id)}})
    if params.min_price is not None:
        filters.append({"range": {"price": {"gte": float(params.min_price)}}})
    if params.max_price is not None:
        filters.append({"range": {"price": {"lte": float(params.max_price)}}})

    query: dict = {"bool": {"filter": filters}}
    if params.q:
        query["bool"]["must"] = [
            {"multi_match": {"query": params.q, "fields": ["name", "description"]}}
        ]

    if params.sort == "relevance":
        sort: list[dict] = [{"_score": {"order": params.order}}]
    else:
        field_name = "name.keyword" if params.sort == "name" else params.sort
        sort = [{field_name: {"order": params.order}}]

    return {
        "query": query,
        "sort": sort,
        "from": params.offset,
        "size": params.limit,
        "track_total_hits": True,
        "aggs": {
            "by_category": {"terms": {"field": "category_id", "size": 100}},
            "price_ranges": {
                "range": {
                    "field": "price",
                    "ranges": [
                        {"to": 25},
                        {"from": 25, "to": 50},
                        {"from": 50, "to": 100},
                        {"from": 100},
                    ],
                }
            },
        },
    }


def _map_facets(aggregations: dict | None) -> dict:
    """Перекладывает агрегации ES в стабильные фасеты (без сount утечки DSL)."""
    facets: dict = {}
    for name in ("by_category", "price_ranges"):
        agg = (aggregations or {}).get(name)
        if not agg:
            continue
        facets[name] = [
            {"key": bucket.get("key"), "count": bucket.get("doc_count", 0)}
            for bucket in (agg.get("buckets") or [])
        ]
    return facets


def _source_to_result(source: dict) -> ProductSearchResult:
    """Преобразует ``_source`` в стабильный DTO (цена строкой, даты из epoch)."""
    return ProductSearchResult(
        id=uuid.UUID(source["id"]),
        sku=source["sku"],
        name=source["name"],
        description=source.get("description"),
        category_id=uuid.UUID(source["category_id"]),
        category_name=source["category_name"],
        price=str(Decimal(str(source["price"]))),
        currency=source["currency"],
        attributes=source.get("attributes") or {},
        is_active=source["is_active"],
        created_at=datetime.fromtimestamp(source["created_at"] / 1000, tz=UTC),
        updated_at=datetime.fromtimestamp(source["updated_at"] / 1000, tz=UTC),
    )


def _unavailable() -> HTTPException:
    """503 ``SEARCH_UNAVAILABLE`` для breaker-open/подключения к ES."""
    catalog_search_unavailable_total.inc()
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=ErrorDetail(
            code="SEARCH_UNAVAILABLE",
            message="Search is temporarily unavailable",
            details=None,
        ).model_dump(),
    )


async def search_products(
    client: AsyncElasticsearch, params: SearchQuery
) -> tuple[list[ProductSearchResult], int, dict]:
    """Выполняет поиск через circuit breaker и маппит результат с фасетами.

    Возвращает:
        Кортеж ``(items, total, facets)``.

    Исключения:
        HTTPException(503): ES недоступен / breaker открыт.
        HTTPException(422): невалидный сортировка (``INVALID_SORT``).
    """
    try:
        body = build_query(params)
    except InvalidSortError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ErrorDetail(
                code="INVALID_SORT",
                message="Unsupported sort key or order",
                details=None,
            ).model_dump(),
        )
    try:
        response = await search_breaker.call(
            client.search, index=CATALOG_INDEX, body=body
        )
    except (TransportError, BreakerOpenError) as exc:
        raise _unavailable() from exc
    total = int(response["hits"]["total"]["value"])
    items = [_source_to_result(hit["_source"]) for hit in response["hits"]["hits"]]
    facets = _map_facets(response.get("aggregations"))
    return items, total, facets
