"""Интеграционные тесты каталога на PostgreSQL через HTTP (8.2).

Каждый тест создаёт собственные данные (уникальные name/sku), поэтому
допустимо общее сессионное состояние БД.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.models.outbox import IndexOutbox as OutboxEvent

_F = "/api/v1"


def _u(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _detail(resp) -> dict:
    return resp.json()["error"]


class TestHealth:
    async def test_live_returns_ok(self, client):
        resp = await client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "alive"}

    async def test_ready_returns_ok_via_engine(self, client):
        resp = await client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}


class TestCategories:
    async def _create(self, client, name=None, description="desc"):
        resp = await client.post(
            f"{_F}/categories",
            json={"name": name or _u("cat"), "description": description},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    async def test_create_and_get_category(self, client):
        created = await self._create(client)
        assert created["name"]
        assert created["description"] == "desc"

        got = await client.get(f"{_F}/categories/{created['id']}")
        assert got.status_code == 200
        assert got.json()["id"] == created["id"]

    async def test_duplicate_category_name_returns_409(self, client):
        name = _u("dup-cat")
        await self._create(client, name=name)
        resp = await client.post(f"{_F}/categories", json={"name": name})
        assert resp.status_code == 409
        assert _detail(resp)["code"] == "DUPLICATE_CATEGORY"

    async def test_invalid_category_name_returns_422(self, client):
        resp = await client.post(f"{_F}/categories", json={"name": " "})
        assert resp.status_code == 422
        assert _detail(resp)["code"] == "VALIDATION_ERROR"

    async def test_get_missing_category_returns_404(self, client):
        resp = await client.get(f"{_F}/categories/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert _detail(resp)["code"] == "CATEGORY_NOT_FOUND"

    async def test_list_categories(self, client):
        await self._create(client)
        resp = await client.get(f"{_F}/categories")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1

    async def test_patch_category(self, client):
        created = await self._create(client)
        resp = await client.patch(
            f"{_F}/categories/{created['id']}", json={"description": "updated"}
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "updated"

    async def test_patch_category_duplicate_name_returns_409(self, client):
        name_a, name_b = _u("a"), _u("b")
        cat_a = await self._create(client, name=name_a)
        await self._create(client, name=name_b)
        resp = await client.patch(
            f"{_F}/categories/{cat_a['id']}", json={"name": name_b}
        )
        assert resp.status_code == 409
        assert _detail(resp)["code"] == "DUPLICATE_CATEGORY"

    async def test_delete_category_with_products_is_restricted(self, client):
        category = await self._create(client)
        product = await self._create_product(client, category["id"])
        resp = await client.delete(f"{_F}/categories/{category['id']}")
        assert resp.status_code == 409
        assert _detail(resp)["code"] == "CATEGORY_HAS_PRODUCTS"
        # товар остался на месте
        got = await client.get(f"{_F}/products/{product['id']}")
        assert got.status_code == 200

    async def test_delete_empty_category(self, client):
        category = await self._create(client)
        resp = await client.delete(f"{_F}/categories/{category['id']}")
        assert resp.status_code == 204
        assert (
            await client.get(f"{_F}/categories/{category['id']}")
        ).status_code == 404

    async def _create_product(self, client, category_id: str) -> dict:
        resp = await client.post(
            f"{_F}/products",
            json={
                "category_id": category_id,
                "name": _u("prod"),
                "price": "12.50",
                "currency": "USD",
                "sku": _u("SKU"),
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()


class TestProducts:
    async def _seed(self, client) -> dict:
        resp = await client.post(f"{_F}/categories", json={"name": _u("cat")})
        assert resp.status_code == 201
        category_id = resp.json()["id"]
        products = []
        for i, name in enumerate(["Alpha One", "Beta Two", "Gamma Three"]):
            resp = await client.post(
                f"{_F}/products",
                json={
                    "category_id": category_id,
                    "name": name,
                    "description": f"description for {name.lower()}",
                    "price": f"{10 + i}.00",
                    "currency": "USD",
                    "sku": _u("SKU"),
                    "is_active": i != 1,
                },
            )
            assert resp.status_code == 201, resp.text
            products.append(resp.json())
        return {"category_id": category_id, "products": products}

    async def test_create_and_get_product(self, client):
        cat_id = (await client.post(f"{_F}/categories", json={"name": _u("c")})).json()[
            "id"
        ]
        resp = await client.post(
            f"{_F}/products",
            json={
                "category_id": cat_id,
                "name": "Wireless Mouse",
                "price": "19.99",
                "currency": "USD",
                "sku": _u("SKU"),
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Wireless Mouse"
        assert body["price"] == "19.99"
        assert body["is_active"] is True
        assert body["attributes"] == {}

        got = await client.get(f"{_F}/products/{body['id']}")
        assert got.status_code == 200
        assert got.json()["sku"] == body["sku"]

    async def test_duplicate_sku_returns_409(self, client):
        cat_id = (await client.post(f"{_F}/categories", json={"name": _u("c")})).json()[
            "id"
        ]
        sku = _u("SKU")
        payload = {
            "category_id": cat_id,
            "name": "A",
            "price": "1.00",
            "currency": "USD",
            "sku": sku,
        }
        assert (await client.post(f"{_F}/products", json=payload)).status_code == 201
        resp = await client.post(f"{_F}/products", json=payload)
        assert resp.status_code == 409
        assert _detail(resp)["code"] == "DUPLICATE_SKU"

    async def test_product_unknown_category_returns_422(self, client):
        resp = await client.post(
            f"{_F}/products",
            json={
                "category_id": str(uuid.uuid4()),
                "name": "Orphan",
                "price": "5.00",
                "currency": "USD",
                "sku": _u("SKU"),
            },
        )
        assert resp.status_code == 422
        assert _detail(resp)["code"] == "INVALID_CATEGORY"

    async def test_product_invalid_price_returns_422(self, client):
        cat_id = (await client.post(f"{_F}/categories", json={"name": _u("c")})).json()[
            "id"
        ]
        resp = await client.post(
            f"{_F}/products",
            json={
                "category_id": cat_id,
                "name": "X",
                "price": "-1",
                "currency": "USD",
                "sku": _u("S"),
            },
        )
        assert resp.status_code == 422
        assert _detail(resp)["code"] == "VALIDATION_ERROR"

    async def test_get_missing_product_returns_404(self, client):
        resp = await client.get(f"{_F}/products/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert _detail(resp)["code"] == "PRODUCT_NOT_FOUND"

    async def test_list_default_hides_inactive(self, client):
        await self._seed(client)
        resp = await client.get(f"{_F}/products")
        assert resp.status_code == 200
        body = resp.json()
        names = {p["name"] for p in body["items"]}
        assert "Alpha One" in names and "Gamma Three" in names
        assert "Beta Two" not in names

    async def test_list_is_active_param(self, client):
        await self._seed(client)
        resp = await client.get(f"{_F}/products?is_active=false")
        names = {p["name"] for p in resp.json()["items"]}
        assert "Beta Two" in names
        assert "Alpha One" not in names

    async def test_list_filter_and_pagination(self, client):
        data = await self._seed(client)
        category_id = data["category_id"]
        resp = await client.get(
            f"{_F}/products", params={"category_id": category_id, "limit": 1}
        )
        body = resp.json()
        assert body["total"] == 2  # Beta Two неактивен и по умолчанию скрыт
        assert len(body["items"]) == 1

        resp = await client.get(
            f"{_F}/products",
            params={"category_id": category_id, "limit": 1, "offset": 1},
        )
        assert len(resp.json()["items"]) == 1

        resp = await client.get(
            f"{_F}/products", params={"category_id": str(uuid.uuid4())}
        )
        assert resp.json()["total"] == 0

    async def test_list_sort_by_price_name(self, client):
        data = await self._seed(client)
        category_id = data["category_id"]
        resp = await client.get(
            f"{_F}/products",
            params={"category_id": category_id, "sort": "price", "order": "asc"},
        )
        prices = [Decimal(p["price"]) for p in resp.json()["items"]]
        assert prices == sorted(prices)

        resp = await client.get(
            f"{_F}/products",
            params={"category_id": category_id, "sort": "name", "order": "asc"},
        )
        names = [p["name"] for p in resp.json()["items"]]
        assert names == sorted(names)

    async def test_list_invalid_sort_returns_422(self, client):
        resp = await client.get(f"{_F}/products", params={"sort": "bogus"})
        assert resp.status_code == 422
        assert _detail(resp)["code"] == "INVALID_SORT"

    async def test_patch_product(self, client):
        data = await self._seed(client)
        product_id = data["products"][0]["id"]
        resp = await client.patch(
            f"{_F}/products/{product_id}", json={"price": "99.00", "is_active": False}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["price"] == "99.00"
        assert body["is_active"] is False

    async def test_patch_product_duplicate_sku_returns_409(self, client):
        data = await self._seed(client)
        first, second = data["products"][0], data["products"][1]
        resp = await client.patch(
            f"{_F}/products/{second['id']}", json={"sku": first["sku"]}
        )
        assert resp.status_code == 409
        assert _detail(resp)["code"] == "DUPLICATE_SKU"

    async def test_patch_missing_product_returns_404(self, client):
        resp = await client.patch(f"{_F}/products/{uuid.uuid4()}", json={"name": "x"})
        assert resp.status_code == 404

    async def test_delete_product_then_delete_category(self, client):
        resp = await client.post(f"{_F}/categories", json={"name": _u("c")})
        category_id = resp.json()["id"]
        product = (
            await client.post(
                f"{_F}/products",
                json={
                    "category_id": category_id,
                    "name": "Solo",
                    "price": "1.00",
                    "currency": "USD",
                    "sku": _u("SKU"),
                },
            )
        ).json()
        assert (
            await client.delete(f"{_F}/products/{product['id']}")
        ).status_code == 204
        assert (await client.get(f"{_F}/products/{product['id']}")).status_code == 404
        resp = await client.delete(f"{_F}/categories/{category_id}")
        assert resp.status_code == 204


class TestOutbox:
    async def _events(self, db_session) -> list[OutboxEvent]:
        result = await db_session.scalars(
            select(OutboxEvent).order_by(OutboxEvent.created_at.desc()).limit(50)
        )
        return list(result)

    async def test_crud_events_are_enqueued(self, client, db_session):
        before = await db_session.scalar(select(func.count()).select_from(OutboxEvent))
        before = before or 0

        cat_id = (await client.post(f"{_F}/categories", json={"name": _u("c")})).json()[
            "id"
        ]
        product = (
            await client.post(
                f"{_F}/products",
                json={
                    "category_id": cat_id,
                    "name": "Eventy",
                    "price": "1.00",
                    "currency": "USD",
                    "sku": _u("SKU"),
                },
            )
        ).json()
        pid = product["id"]
        await client.patch(f"{_F}/products/{pid}", json={"price": "2.00"})
        assert (await client.delete(f"{_F}/products/{pid}")).status_code == 204

        events = await self._events(db_session)
        assert (
            await db_session.scalar(select(func.count()).select_from(OutboxEvent))
        ) == before + 3
        event_types = {e.envelope["event_type"] for e in events[:3]}
        assert event_types == {"product.created", "product.updated", "product.deleted"}
        for e in events[:3]:
            assert e.status == "pending"
            assert e.envelope["event_version"] == 1
            assert "id" in e.envelope["payload"]
        assert {e.envelope["payload"]["id"] for e in events[:3]} == {pid}
        created = next(
            e for e in events[:3] if e.envelope["event_type"] == "product.created"
        )
        assert created.envelope["payload"]["name"] == "Eventy"
        assert created.envelope["payload"]["price"] == "1.00"

    async def test_failed_write_leaves_no_outbox_row(self, client, db_session):
        before = await db_session.scalar(select(func.count()).select_from(OutboxEvent))
        before = before or 0

        resp = await client.post(
            f"{_F}/products",
            json={
                "category_id": str(uuid.uuid4()),  # несуществующая категория
                "name": "Ghost",
                "price": "1.00",
                "currency": "USD",
                "sku": _u("SKU"),
            },
        )
        assert resp.status_code == 422
        count = await db_session.scalar(select(func.count()).select_from(OutboxEvent))
        assert count == before


class TestProductCache:
    async def test_get_product_with_cache_enabled_returns_product(self, client):
        import app.cache

        app.cache.init()
        try:
            cat_id = (
                await client.post(f"{_F}/categories", json={"name": _u("cached cat")})
            ).json()["id"]
            product = (
                await client.post(
                    f"{_F}/products",
                    json={
                        "category_id": cat_id,
                        "name": "Cached Widget",
                        "price": "12.50",
                        "currency": "USD",
                        "sku": _u("CACHE-SKU"),
                    },
                )
            ).json()

            resp = await client.get(f"{_F}/products/{product['id']}")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["id"] == product["id"]
            assert body["price"] == "12.50"

            resp2 = await client.get(f"{_F}/products/{product['id']}")
            assert resp2.status_code == 200
            assert resp2.json()["name"] == "Cached Widget"

            assert (
                await client.delete(f"{_F}/products/{product['id']}")
            ).status_code == 204
            assert (
                await client.get(f"{_F}/products/{product['id']}")
            ).status_code == 404
        finally:
            await app.cache.close()
