"""Юнит-тесты построения ES-запроса из публичных параметров (8.1)."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.search import InvalidSortError, SearchQuery, build_query


def test_empty_q_is_match_all_with_active_filter():
    body = build_query(SearchQuery())
    assert body["query"] == {"bool": {"filter": [{"term": {"is_active": True}}]}}
    assert "must" not in body["query"]["bool"]


def test_q_produces_multi_match_on_name_and_description():
    body = build_query(SearchQuery(q="  wireless  "))
    must = body["query"]["bool"]["must"]
    assert must == [
        {"multi_match": {"query": "wireless", "fields": ["name", "description"]}}
    ]


def test_filters_category_and_price_range():
    category_id = uuid4()
    body = build_query(
        SearchQuery(
            category_id=category_id,
            min_price=Decimal("10.00"),
            max_price=Decimal("99.99"),
        )
    )
    filters = body["query"]["bool"]["filter"]
    assert {"term": {"category_id": str(category_id)}} in filters
    assert {"range": {"price": {"gte": 10.0}}} in filters
    assert {"range": {"price": {"lte": 99.99}}} in filters


def test_active_filter_is_always_first():
    body = build_query(SearchQuery(q="x", category_id=uuid4()))
    assert body["query"]["bool"]["filter"][0] == {"term": {"is_active": True}}


def test_sort_price_and_name_keyword():
    assert build_query(SearchQuery(sort="price"))["sort"] == [
        {"price": {"order": "desc"}}
    ]
    assert build_query(SearchQuery(sort="created_at", order="asc"))["sort"] == [
        {"created_at": {"order": "asc"}}
    ]
    assert build_query(SearchQuery(sort="name"))["sort"] == [
        {"name.keyword": {"order": "desc"}}
    ]


def test_sort_relevance_uses_score():
    assert build_query(SearchQuery(sort="relevance"))["sort"] == [
        {"_score": {"order": "desc"}}
    ]


def test_invalid_sort_rejected():
    with pytest.raises(InvalidSortError):
        SearchQuery(sort="unknown")


def test_invalid_order_rejected():
    with pytest.raises(InvalidSortError):
        SearchQuery(order="sideways")


def test_limit_clamped_to_max_and_min():
    assert SearchQuery(limit=1000).limit == 100
    assert SearchQuery(limit=0).limit == 1


def test_paging_and_track_total_hits():
    body = build_query(SearchQuery(limit=10, offset=25))
    assert body["from"] == 25
    assert body["size"] == 10
    assert body["track_total_hits"] is True


def test_query_carries_facets_aggregations():
    body = build_query(SearchQuery())
    aggs = body["aggs"]
    assert "by_category" in aggs
    assert aggs["by_category"]["terms"]["field"] == "category_id"
    assert "price_ranges" in aggs
    assert aggs["price_ranges"]["range"]["field"] == "price"
