"""Интеграционные тесты резервов: атомарность, идемпотентность, конкуррентность (фаза 4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.usefixtures("db_engine")


def _session(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)()


async def _make_stock(client, sku, on_hand):
    resp = await client.post(
        "/stock-items", json={"sku": sku, "quantity_on_hand": on_hand}
    )
    assert resp.status_code == 201
    return resp.json()


class TestRepositoryReserve:
    async def test_reserve_success(self, client, db_engine) -> None:
        await _make_stock(client, "RR-1", 100)
        session = _session(db_engine)
        async with session as s:
            from app.repositories.reservation_repo import ReservationRepository
            from app.repositories.stock_repo import StockRepository

            item = await StockRepository(s).get_by_sku("RR-1")
            reservation = await ReservationRepository(s).reserve(
                stock_item_id=item.id,
                quantity=30,
                holder_ref="o-1",
                idempotency_key=None,
                expires_at=datetime.now(UTC) + timedelta(seconds=60),
            )
            await s.commit()
            assert reservation.status == "active"
            assert reservation.quantity == 30
            reserved_after = await StockRepository(s).get_by_sku("RR-1")
            assert reserved_after.quantity_reserved == 30
            assert reserved_after.available == 70

    async def test_reserve_beyond_available_fails_no_change(
        self, client, db_engine
    ) -> None:
        await _make_stock(client, "RR-2", 10)
        session = _session(db_engine)
        async with session as s:
            from app.repositories.reservation_repo import ReservationRepository
            from app.repositories.stock_repo import StockRepository

            item = await StockRepository(s).get_by_sku("RR-2")
            assert (
                await ReservationRepository(s).reserve(
                    stock_item_id=item.id,
                    quantity=11,
                    holder_ref="o-2",
                    idempotency_key=None,
                    expires_at=datetime.now(UTC) + timedelta(seconds=60),
                )
                is None
            )
            await s.rollback()
            reserved_after = await StockRepository(s).get_by_sku("RR-2")
            assert reserved_after.quantity_reserved == 0
            assert reserved_after.available == 10


class TestReservationApi:
    async def test_reserve_201(self, client) -> None:
        await _make_stock(client, "API-R1", 50)
        resp = await client.post(
            "/reservations",
            json={"sku": "API-R1", "quantity": 10, "holder_ref": "order-1"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "active"
        assert body["quantity"] == 10
        assert body["expires_at"] > body["created_at"]

    async def test_reserve_unknown_sku_404(self, client) -> None:
        resp = await client.post(
            "/reservations",
            json={"sku": "GHOST", "quantity": 1, "holder_ref": "o"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "STOCK_ITEM_NOT_FOUND"

    async def test_reserve_insufficient_409(self, client) -> None:
        await _make_stock(client, "API-R2", 5)
        resp = await client.post(
            "/reservations",
            json={"sku": "API-R2", "quantity": 6, "holder_ref": "o"},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "INSUFFICIENT_STOCK"
        after = await client.get("/stock-items/by-sku/API-R2")
        assert after.json()["quantity_reserved"] == 0

    async def test_idempotency_key_returns_same_reservation(self, client) -> None:
        await _make_stock(client, "API-R3", 100)
        first = await client.post(
            "/reservations",
            json={"sku": "API-R3", "quantity": 5, "holder_ref": "o"},
            headers={"Idempotency-Key": "key-1"},
        )
        assert first.status_code == 201
        second = await client.post(
            "/reservations",
            json={"sku": "API-R3", "quantity": 5, "holder_ref": "o"},
            headers={"Idempotency-Key": "key-1"},
        )
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        after = await client.get("/stock-items/by-sku/API-R3")
        assert after.json()["quantity_reserved"] == 5

    async def test_ttl_override(self, client) -> None:
        await _make_stock(client, "API-R4", 10)
        resp = await client.post(
            "/reservations",
            json={
                "sku": "API-R4",
                "quantity": 1,
                "holder_ref": "o",
                "ttl_seconds": 30,
            },
        )
        body = resp.json()
        created = datetime.fromisoformat(body["created_at"])
        expires = datetime.fromisoformat(body["expires_at"])
        assert 29 <= (expires - created).total_seconds() <= 31


class TestNoOversellConcurrency:
    async def test_20_parallel_never_oversell(self, client, db_engine) -> None:
        """4.4: 20 параллельных резервов по 10 при available 100."""
        await _make_stock(client, "CC-1", 100)

        async def reserve(i: int):
            resp = await client.post(
                "/reservations",
                json={"sku": "CC-1", "quantity": 10, "holder_ref": f"o-{i}"},
            )
            return resp.status_code, resp.json()

        results = await asyncio.gather(*(reserve(i) for i in range(20)))
        succeeded = [r for r in results if r[0] == 201]
        rejected = [r for r in results if r[0] == 409]
        assert len(succeeded) == 10
        assert len(rejected) == 10
        for _, body in rejected:
            assert body["error"]["code"] == "INSUFFICIENT_STOCK"

        after = await client.get("/stock-items/by-sku/CC-1")
        assert after.json()["quantity_reserved"] == 100
        assert after.json()["quantity_on_hand"] == 100
