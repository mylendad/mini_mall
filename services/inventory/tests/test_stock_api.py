"""Интеграционные тесты складских позиций: репозиторий и API (фаза 2)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("db_engine")


async def _create(client, sku="SKU-1", on_hand=100, threshold=0):
    resp = await client.post(
        "/stock-items",
        json={"sku": sku, "quantity_on_hand": on_hand, "low_stock_threshold": threshold},
    )
    return resp


class TestRepository:
    async def test_create_and_gets(self, db_session) -> None:
        from app.repositories.stock_repo import StockRepository

        repo = StockRepository(db_session)
        item = await repo.create(sku="R-1", quantity_on_hand=10, low_stock_threshold=2)
        assert item.sku == "R-1"
        assert item.quantity_reserved == 0
        assert item.available == 10
        assert (await repo.get_by_id(item.id)).id == item.id
        assert (await repo.get_by_sku("R-1")).id == item.id

    async def test_list_pagination(self, db_session) -> None:
        from app.repositories.stock_repo import StockRepository

        repo = StockRepository(db_session)
        for i in range(5):
            await repo.create(sku=f"L-{i}", quantity_on_hand=i)
        page, total = await repo.list(offset=0, limit=3)
        assert total >= 5
        assert len(page) == 3

    async def test_adjust_negative_rejected_without_change(self, db_session) -> None:
        from app.repositories.stock_repo import StockRepository

        repo = StockRepository(db_session)
        item = await repo.create(sku="A-1", quantity_on_hand=5)
        assert await repo.adjust_quantity(item, -6) is None
        after = await repo.get_by_sku("A-1")
        assert after.quantity_on_hand == 5

    async def test_adjust_positive_and_negative_ok(self, db_session) -> None:
        from app.repositories.stock_repo import StockRepository

        repo = StockRepository(db_session)
        item = await repo.create(sku="A-2", quantity_on_hand=10)
        await repo.adjust_quantity(item, -4)
        after = await repo.get_by_sku("A-2")
        assert after.quantity_on_hand == 6
        await repo.adjust_quantity(after, 10)
        assert (await repo.get_by_sku("A-2")).quantity_on_hand == 16

    async def test_update_threshold(self, db_session) -> None:
        from app.repositories.stock_repo import StockRepository

        repo = StockRepository(db_session)
        item = await repo.create(sku="T-1", quantity_on_hand=1)
        await repo.update_threshold(item, 7)
        assert (await repo.get_by_sku("T-1")).low_stock_threshold == 7

    async def test_batch_availability(self, db_session) -> None:
        from app.repositories.stock_repo import StockRepository

        repo = StockRepository(db_session)
        await repo.create(sku="B-1", quantity_on_hand=10)
        await repo.create(sku="B-2", quantity_on_hand=5)
        found = await repo.get_availability_batch(["B-1", "B-2", "B-missing"])
        assert found["B-1"] == (10, 0)
        assert found["B-2"] == (5, 0)
        assert "B-missing" not in found


class TestApi:
    async def test_create_201(self, client) -> None:
        resp = await _create(client, "API-1", 100)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["sku"] == "API-1"
        assert body["quantity_on_hand"] == 100
        assert body["available"] == 100
        assert body["quantity_reserved"] == 0

    async def test_create_duplicate_sku_409(self, client) -> None:
        await _create(client, "DUP-1", 1)
        resp = await _create(client, "DUP-1", 2)
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "DUPLICATE_SKU"
        assert body["error"]["message"] == "Stock item SKU already exists"
        assert body["request_id"]

    async def test_get_unknown_404(self, client) -> None:
        resp = await client.get("/stock-items/by-sku/UNKNOWN")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "STOCK_ITEM_NOT_FOUND"

    async def test_get_by_sku_and_id(self, client) -> None:
        created = (await _create(client, "GET-1", 7)).json()
        by_sku = await client.get("/stock-items/by-sku/GET-1")
        assert by_sku.status_code == 200
        by_id = await client.get(f"/stock-items/{created['id']}")
        assert by_id.status_code == 200
        assert by_id.json()["sku"] == "GET-1"

    async def test_list_paginated(self, client) -> None:
        for i in range(3):
            await _create(client, f"PL-{i}", i)
        resp = await client.get("/stock-items", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 3
        assert len(body["items"]) == 2

    async def test_negative_adjustment_422(self, client) -> None:
        created = (await _create(client, "NEG-1", 5)).json()
        resp = await client.post(
            f"/stock-items/{created['id']}/adjustments",
            json={"delta": -10, "reason": "correction"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        after = await client.get(f"/stock-items/{created['id']}")
        assert after.json()["quantity_on_hand"] == 5

    async def test_adjustment_ok_and_event_outbox(self, client, db_engine) -> None:
        created = (await _create(client, "ADJ-1", 10)).json()
        resp = await client.post(
            f"/stock-items/{created['id']}/adjustments",
            json={"delta": 5, "reason": "receipt"},
        )
        assert resp.status_code == 200
        assert resp.json()["quantity_on_hand"] == 15
        from sqlalchemy import select

        from app.models.outbox import InventoryOutbox

        session = async_session_maker(db_engine)()
        async with session:
            rows = (
                (
                    await session.execute(
                        select(InventoryOutbox).order_by(InventoryOutbox.created_at)
                    )
                )
                .scalars()
                .all()
            )
        types = [r.envelope["event_type"] for r in rows]
        assert "inventory.stock_item.created" in types
        assert "inventory.stock.adjusted" in types

    async def test_threshold_update(self, client) -> None:
        created = (await _create(client, "TH-1", 10)).json()
        resp = await client.patch(
            f"/stock-items/{created['id']}", json={"low_stock_threshold": 3}
        )
        assert resp.status_code == 200
        assert resp.json()["low_stock_threshold"] == 3

    async def test_threshold_update_unknown_404(self, client) -> None:
        import uuid

        resp = await client.patch(
            f"/stock-items/{uuid.uuid4()}", json={"low_stock_threshold": 1}
        )
        assert resp.status_code == 404

    async def test_derived_available_contract(self, client, db_session) -> None:
        """2.5: available = on_hand - reserved в каждом ответе."""
        created = (await _create(client, "DER-1", 30)).json()
        assert created["available"] == 30
        from datetime import UTC, datetime, timedelta

        from app.repositories.reservation_repo import ReservationRepository
        from app.repositories.stock_repo import StockRepository

        repo = StockRepository(db_session)
        item = await repo.get_by_sku("DER-1")
        res_repo = ReservationRepository(db_session)
        await res_repo.reserve(
            stock_item_id=item.id,
            quantity=10,
            holder_ref="o1",
            idempotency_key=None,
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        await db_session.commit()
        fetched = await client.get(f"/stock-items/{created['id']}")
        body = fetched.json()
        assert body["quantity_reserved"] == 10
        assert body["available"] == body["quantity_on_hand"] - body["quantity_reserved"] == 20


def async_session_maker(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(engine, expire_on_commit=False)
