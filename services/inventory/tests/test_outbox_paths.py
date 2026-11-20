"""Интеграционные тесты outbox-событий на всех записывающих путях (7.3) и low-stock (8.2)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.usefixtures("db_engine")


def _session(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)()


async def _outbox_rows(db_engine, sku: str | None = None):
    from app.models.outbox import InventoryOutbox

    session = _session(db_engine)
    async with session as s:
        rows = (
            (await s.execute(select(InventoryOutbox).order_by(InventoryOutbox.id)))
            .scalars()
            .all()
        )
        out = []
        for r in rows:
            env = r.envelope
            out.append(
                {
                    "event_id": r.event_id,
                    "type": env["event_type"],
                    "status": r.status,
                    "sku": (env.get("payload") or {}).get("sku"),
                    "event_type": env["event_type"],
                }
            )
    if sku is not None:
        out = [o for o in out if o["sku"] == sku]
    return out


async def test_stock_item_creation_event(client, db_engine) -> None:
    await client.post(
        "/stock-items", json={"sku": "OW-1", "quantity_on_hand": 10}
    )
    rows = await _outbox_rows(db_engine, "OW-1")
    assert [r["event_type"] for r in rows] == ["inventory.stock_item.created"]


async def test_adjustment_event(client, db_engine) -> None:
    created = (
        await client.post(
            "/stock-items", json={"sku": "OW-2", "quantity_on_hand": 10}
        )
    ).json()
    await client.post(
        f"/stock-items/{created['id']}/adjustments",
        json={"delta": 5, "reason": "receipt"},
    )
    rows = await _outbox_rows(db_engine, "OW-2")
    types = [r["event_type"] for r in rows]
    assert "inventory.stock_item.created" in types
    assert "inventory.stock.adjusted" in types


async def test_threshold_event(client, db_engine) -> None:
    created = (
        await client.post(
            "/stock-items", json={"sku": "OW-3", "quantity_on_hand": 10}
        )
    ).json()
    await client.patch(
        f"/stock-items/{created['id']}", json={"low_stock_threshold": 5}
    )
    rows = await _outbox_rows(db_engine, "OW-3")
    assert any(r["event_type"] == "inventory.threshold.updated" for r in rows)


async def test_reservation_lifecycle_events(client, db_engine) -> None:
    await client.post(
        "/stock-items", json={"sku": "OW-4", "quantity_on_hand": 100}
    )
    r = (
        await client.post(
            "/reservations",
            json={"sku": "OW-4", "quantity": 10, "holder_ref": "o"},
        )
    ).json()
    await client.post(f"/reservations/{r['id']}/confirm")
    r2 = (
        await client.post(
            "/reservations",
            json={"sku": "OW-4", "quantity": 5, "holder_ref": "o2"},
        )
    ).json()
    await client.post(f"/reservations/{r2['id']}/release")
    rows = await _outbox_rows(db_engine, "OW-4")
    types = [r["event_type"] for r in rows]
    assert "inventory.reserved" in types
    assert "inventory.confirmed" in types
    assert "inventory.released" in types


async def test_expiration_event(client, db_engine) -> None:
    await client.post(
        "/stock-items", json={"sku": "OW-5", "quantity_on_hand": 100}
    )
    await client.post(
        "/reservations",
        json={"sku": "OW-5", "quantity": 3, "holder_ref": "o", "ttl_seconds": 1},
    )
    import asyncio

    await asyncio.sleep(1.1)
    from app.services.expiration import expire_batch

    await expire_batch(limit=100)
    rows = await _outbox_rows(db_engine, "OW-5")
    assert any(
        r["event_type"] == "inventory.reservation.expired" for r in rows
    )


async def test_failed_operation_leaves_neither_state_nor_event(
    client, db_engine
) -> None:
    """Rollback-тест: неудачная операция не оставляет ни изменения, ни события."""
    created = (
        await client.post(
            "/stock-items", json={"sku": "OW-6", "quantity_on_hand": 5}
        )
    ).json()
    before_rows = await _outbox_rows(db_engine, "OW-6")
    resp = await client.post(
        f"/stock-items/{created['id']}/adjustments",
        json={"delta": -10, "reason": "bad"},
    )
    assert resp.status_code == 422
    after_rows = await _outbox_rows(db_engine, "OW-6")
    assert after_rows == before_rows  # ни события
    item = (await client.get("/stock-items/by-sku/OW-6")).json()
    assert item["quantity_on_hand"] == 5  # ни изменения состояния

    resp = await client.post(
        "/reservations",
        json={"sku": "OW-6", "quantity": 50, "holder_ref": "o"},
    )
    assert resp.status_code == 409
    after_rows2 = await _outbox_rows(db_engine, "OW-6")
    assert after_rows2 == before_rows  # ни события резерва
    assert item["quantity_reserved"] == 0


class TestLowStockEvents:
    async def test_reserve_crossing_emits_once(self, client, db_engine) -> None:
        await client.post(
            "/stock-items",
            json={"sku": "LS-1", "quantity_on_hand": 15, "low_stock_threshold": 10},
        )
        await client.post(
            "/reservations",
            json={"sku": "LS-1", "quantity": 6, "holder_ref": "o"},
        )
        rows = await _outbox_rows(db_engine, "LS-1")
        low = [r for r in rows if r["event_type"] == "inventory.low_stock"]
        assert len(low) == 1

        # Дальнейшее уменьшение ниже порога не переэмитит alert.
        await client.post(
            "/reservations",
            json={"sku": "LS-1", "quantity": 2, "holder_ref": "o2"},
        )
        rows = await _outbox_rows(db_engine, "LS-1")
        low = [r for r in rows if r["event_type"] == "inventory.low_stock"]
        assert len(low) == 1

    async def test_restock_rearms_alert(self, client, db_engine) -> None:
        created = (
            await client.post(
                "/stock-items",
                json={"sku": "LS-2", "quantity_on_hand": 12, "low_stock_threshold": 10},
            )
        ).json()
        await client.post(
            "/reservations",
            json={"sku": "LS-2", "quantity": 5, "holder_ref": "o"},
        )  # available 7 < 10 -> alert
        rows = await _outbox_rows(db_engine, "LS-2")
        assert len([r for r in rows if r["event_type"] == "inventory.low_stock"]) == 1

        # Restock выше порога перезаряжает alert.
        await client.post(
            f"/stock-items/{created['id']}/adjustments",
            json={"delta": 20, "reason": "receipt"},
        )  # available 27
        rows = await _outbox_rows(db_engine, "LS-2")
        assert len([r for r in rows if r["event_type"] == "inventory.low_stock"]) == 1

        # Новое пересечение вниз — снова alert.
        await client.post(
            "/reservations",
            json={"sku": "LS-2", "quantity": 20, "holder_ref": "o2"},
        )  # available 7
        rows = await _outbox_rows(db_engine, "LS-2")
        assert len([r for r in rows if r["event_type"] == "inventory.low_stock"]) == 2

    async def test_threshold_zero_disabled(self, client, db_engine) -> None:
        await client.post(
            "/stock-items", json={"sku": "LS-3", "quantity_on_hand": 10}
        )
        await client.post(
            "/reservations",
            json={"sku": "LS-3", "quantity": 10, "holder_ref": "o"},
        )
        rows = await _outbox_rows(db_engine, "LS-3")
        assert not [r for r in rows if r["event_type"] == "inventory.low_stock"]
