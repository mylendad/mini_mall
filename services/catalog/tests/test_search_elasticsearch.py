"""Интеграционные тесты Elasticsearch: mapping, поиск, релей, реиндекс (8.3).

Порядок ``client`` -> ``db_session`` -> ``es_client`` гарантирует, что сессия
БД закоммитит изменения (переопределённый ``get_db``), перед тем как
``process_outbox`` перечитает продукты из PostgreSQL. Breaker между тестами
сбрасывается, чтобы одиночная ошибка ES не влияла на последующие тесты.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app import elasticsearch as es
from app.models.outbox import IndexOutbox
from app.services.breaker import relay_breaker, search_breaker
from app.services.indexer import ensure_index as ensure_index_fn
from app.services.relay import process_outbox

_F = "/api/v1"


def _u(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


async def _process_and_refresh(db_session) -> tuple[int, int]:
    """`process_outbox` + refresh индекса, чтобы результаты были сразу видны.

    В проде релей идёт фоном и документ может появиться с задержкой
    авто-refresh; в тесте нам нужна детерминированность.
    """
    processed, failed = await process_outbox(db_session)
    await es.es_client.indices.refresh(index=es.CATALOG_INDEX)
    return processed, failed


def _reset_breaker() -> None:
    for breaker in (search_breaker, relay_breaker):
        breaker._consecutive_failures = 0
        breaker._state = "closed"
        breaker._opened_at = 0.0


async def _create_category(client, name: str | None = None) -> str:
    resp = await client.post(f"{_F}/categories", json={"name": name or _u("cat")})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_product(
    client, category_id: str, *, name: str, sku: str | None = None, price: str = "10.00"
) -> dict:
    resp = await client.post(
        f"{_F}/products",
        json={
            "category_id": category_id,
            "name": name,
            "description": f"fluffy {name}",
            "price": price,
            "currency": "USD",
            "sku": sku or _u("SKU"),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def es_index(es_client):
    await es.delete_index(es_client)
    await ensure_index_fn(es_client)
    await es_client.cluster.health(
        index=es.CATALOG_INDEX, wait_for_status="green", timeout="120s"
    )
    _reset_breaker()
    yield


@pytest.fixture(autouse=True)
async def _clean_catalog_db(db_session):
    """Очищает каталог перед каждым тестом поиска.

    PostgreSQL-контейнер сессионный и между тестами накапливает строки,
    поэтому точные ассерты требуют чистого старта: сначала удаляем outbox,
    затем продукты (FK категория -> продукт), затем категории.
    """
    from sqlalchemy import text

    await db_session.execute(text("DELETE FROM index_outbox"))
    await db_session.execute(text("DELETE FROM products"))
    await db_session.execute(text("DELETE FROM categories"))
    await db_session.commit()
    yield


class TestMapping:
    async def test_ensure_index_creates_mapping(self, es_index, es_client):
        mapping = (await es_client.indices.get_mapping(index=es.CATALOG_INDEX))[
            es.CATALOG_INDEX
        ]
        props = mapping["mappings"]["properties"]
        assert props["is_active"]["type"] == "boolean"
        assert props["price"]["type"] == "scaled_float"
        assert props["price"]["scaling_factor"] == 100
        assert props["name"]["type"] == "text"
        assert props["name"]["fields"]["keyword"]["type"] == "keyword"
        assert props["attributes"]["type"] == "flattened"

    async def test_ensure_index_is_idempotent(self, es_index, es_client):
        assert await ensure_index_fn(es_client) is False


class TestRelay:
    async def _seed(self, client) -> dict:
        category_id = await _create_category(client)
        product = await _create_product(
            client, category_id, name="Wireless Mouse Alpha"
        )
        await _create_product(client, category_id, name="Wired Keypad Beta")
        inactive = await _create_product(
            client, category_id, name="Wireless Robot Gamma"
        )
        await client.patch(f"{_F}/products/{inactive['id']}", json={"is_active": False})
        return {"category_id": category_id, "active": product}

    async def test_search_finds_after_relay(self, client, db_session, es_index):
        data = await self._seed(client)
        processed, failed = await _process_and_refresh(db_session)
        assert failed == 0
        assert processed >= 3

        resp = await client.get(
            f"{_F}/products/search", params={"q": "Wireless Mouse Alpha"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["name"] == "Wireless Mouse Alpha"
        assert item["price"] == "10.0"  # из ES цена приходит как float
        assert item["category_id"] == data["category_id"]

    async def test_empty_query_returns_only_active(self, client, db_session, es_index):
        await self._seed(client)
        await _process_and_refresh(db_session)
        resp = await client.get(f"{_F}/products/search")
        assert resp.status_code == 200
        body = resp.json()
        names = {i["name"] for i in body["items"]}
        assert "Wireless Mouse Alpha" in names and "Wired Keypad Beta" in names
        assert "Wireless Robot Gamma" not in names  # неактивный исключается фильтром

    async def test_inactive_product_is_indexed_but_not_searchable(
        self, client, db_session, es_client, es_index
    ):
        category_id = await _create_category(client)
        product = await _create_product(client, category_id, name="To Hide")
        await client.patch(f"{_F}/products/{product['id']}", json={"is_active": False})
        await _process_and_refresh(db_session)
        # документ в индексе есть...
        exists = await es_client.exists(index=es.CATALOG_INDEX, id=product["id"])
        assert exists
        # ...но поиск его не возвращает
        resp = await client.get(f"{_F}/products/search", params={"q": "To Hide"})
        assert resp.json()["total"] == 0

    async def test_filters_and_sorting(self, client, db_session, es_index):
        category_id = await _create_category(client)
        await _create_product(client, category_id, name="Cheap Item", price="5.00")
        await _create_product(client, category_id, name="Pricy Item", price="45.00")
        await _process_and_refresh(db_session)

        resp = await client.get(
            f"{_F}/products/search", params={"min_price": "10", "max_price": "50"}
        )
        assert resp.status_code == 200
        assert {i["name"] for i in resp.json()["items"]} == {"Pricy Item"}

        resp = await client.get(
            f"{_F}/products/search", params={"sort": "price", "order": "asc"}
        )
        names = [i["name"] for i in resp.json()["items"]]
        assert names == ["Cheap Item", "Pricy Item"]

        resp = await client.get(
            f"{_F}/products/search", params={"category_id": str(uuid4())}
        )
        assert resp.json()["total"] == 0

    async def test_pagination(self, client, db_session, es_index):
        category_id = await _create_category(client)
        for i in range(3):
            await _create_product(client, category_id, name=f"Item Number {i}")
        await _process_and_refresh(db_session)

        resp = await client.get(
            f"{_F}/products/search", params={"limit": 1, "offset": 0}
        )
        assert resp.json()["total"] == 3
        assert len(resp.json()["items"]) == 1
        resp = await client.get(
            f"{_F}/products/search", params={"limit": 1, "offset": 2}
        )
        assert len(resp.json()["items"]) == 1

    async def test_facets_in_search_response(self, client, db_session, es_index):
        cat1 = await _create_category(client)
        cat2 = await _create_category(client)
        await _create_product(client, cat1, name="Facet One", price="10.00")
        await _create_product(client, cat2, name="Facet Two", price="80.00")
        await _process_and_refresh(db_session)

        resp = await client.get(f"{_F}/products/search")
        assert resp.status_code == 200
        body = resp.json()
        facets = body["facets"]
        assert "by_category" in facets
        by_category = {b["key"]: b["count"] for b in facets["by_category"]}
        assert by_category.get(cat1) == 1
        assert by_category.get(cat2) == 1
        assert sum(b["count"] for b in facets["price_ranges"]) == 2

    async def test_update_reflected_in_search(self, client, db_session, es_index):
        category_id = await _create_category(client)
        product = await _create_product(client, category_id, name="Cerulean Widget")
        await _process_and_refresh(db_session)

        resp = await client.get(f"{_F}/products/search", params={"q": "Cerulean"})
        assert resp.json()["total"] == 1

        resp = await client.patch(
            f"{_F}/products/{product['id']}",
            json={"name": "Amber Gadget", "description": "fluffy Amber Gadget"},
        )
        assert resp.status_code == 200
        await _process_and_refresh(db_session)

        assert (
            await client.get(f"{_F}/products/search", params={"q": "Amber"})
        ).json()["total"] == 1
        assert (
            await client.get(f"{_F}/products/search", params={"q": "Cerulean"})
        ).json()["total"] == 0

    async def test_delete_removes_document(
        self, client, db_session, es_client, es_index
    ):
        category_id = await _create_category(client)
        product = await _create_product(client, category_id, name="Doomed Product")
        await _process_and_refresh(db_session)
        assert await es_client.exists(index=es.CATALOG_INDEX, id=product["id"])

        assert (
            await client.delete(f"{_F}/products/{product['id']}")
        ).status_code == 204
        await _process_and_refresh(db_session)

        assert not await es_client.exists(index=es.CATALOG_INDEX, id=product["id"])
        assert (
            await client.get(f"{_F}/products/search", params={"q": "Doomed"})
        ).json()["total"] == 0

    async def test_process_outbox_marks_rows_processed(
        self, client, db_session, es_index
    ):
        category_id = await _create_category(client)
        await _create_product(client, category_id, name="Solo Product")
        await _process_and_refresh(db_session)

        rows = list((await db_session.execute(select(IndexOutbox))).scalars())
        assert rows
        assert all(r.status == "processed" for r in rows)
        assert all(r.processed_at is not None for r in rows)


class TestAdminReindex:
    async def test_reindex_without_roles_is_open(self, client, db_session, es_index):
        category_id = await _create_category(client)
        await _create_product(client, category_id, name="Reindex Me")
        resp = await client.post(f"{_F}/admin/reindex")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["index"] == es.CATALOG_INDEX
        assert body["reindexed"] == 1

    async def test_reindex_denied_without_admin_role(self, client, es_index):
        resp = await client.post(
            f"{_F}/admin/reindex", headers={"X-User-Roles": "catalog:read"}
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    async def test_reindex_allowed_with_admin_role(self, client, db_session, es_index):
        category_id = await _create_category(client)
        await _create_product(client, category_id, name="Admin Reindex")
        resp = await client.post(
            f"{_F}/admin/reindex", headers={"X-User-Roles": "admin, crm"}
        )
        assert resp.status_code == 200
        assert resp.json()["reindexed"] == 1
        assert (
            await client.get(f"{_F}/products/search", params={"q": "Admin Reindex"})
        ).json()["total"] == 1


class TestSearchUnavailable:
    async def test_search_returns_503_when_es_down(self, client, db_session, es_index):
        original = es.es_client
        _reset_breaker()
        try:
            es.es_client = es.create_client("http://127.0.0.1:1")  # мёртвый порт
            resp = await client.get(f"{_F}/products/search", params={"q": "anything"})
            assert resp.status_code == 503
            assert resp.json()["error"]["code"] == "SEARCH_UNAVAILABLE"
            metrics = (await client.get("/metrics")).text
            assert "catalog_search_unavailable_total" in metrics
        finally:
            await es.es_client.close()
            es.es_client = original
            _reset_breaker()
