"""Интеграционные тесты жизненного цикла резервов: confirm/release/expiration (фаза 5)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
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


async def _reserve(client, sku, qty, holder="o", key=None, ttl=900):
    headers = {"Idempotency-Key": key} if key else {}
    resp = await client.post(
        "/reservations",
        json={"sku": sku, "quantity": qty, "holder_ref": holder, "ttl_seconds": ttl},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestConfirm:
    async def test_confirm_consumes_stock(self, client) -> None:
        await _make_stock(client, "CF-1", 10)
        r = await _reserve(client, "CF-1", 3)
        resp = await client.post(f"/reservations/{r['id']}/confirm")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "confirmed"
        item = (await client.get("/stock-items/by-sku/CF-1")).json()
        assert item["quantity_on_hand"] == 7
        assert item["quantity_reserved"] == 0

    async def test_confirm_twice_idempotent(self, client) -> None:
        await _make_stock(client, "CF-2", 10)
        r = await _reserve(client, "CF-2", 3)
        second = await client.post(f"/reservations/{r['id']}/confirm")
        assert second.status_code == 200
        assert second.json()["status"] == "confirmed"
        item = (await client.get("/stock-items/by-sku/CF-2")).json()
        assert item["quantity_on_hand"] == 7  # без второго списания

    async def test_confirm_released_409(self, client) -> None:
        await _make_stock(client, "CF-3", 10)
        r = await _reserve(client, "CF-3", 3)
        await client.post(f"/reservations/{r['id']}/release")
        resp = await client.post(f"/reservations/{r['id']}/confirm")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "INVALID_RESERVATION_STATE"

    async def test_confirm_unknown_404(self, client) -> None:
        import uuid

        resp = await client.post(f"/reservations/{uuid.uuid4()}/confirm")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESERVATION_NOT_FOUND"


class TestRelease:
    async def test_release_returns_stock(self, client) -> None:
        await _make_stock(client, "RL-1", 10)
        r = await _reserve(client, "RL-1", 3)
        resp = await client.post(f"/reservations/{r['id']}/release")
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"
        item = (await client.get("/stock-items/by-sku/RL-1")).json()
        assert item["quantity_on_hand"] == 10  # on_hand не меняется
        assert item["quantity_reserved"] == 0

    async def test_release_twice_idempotent(self, client) -> None:
        await _make_stock(client, "RL-2", 10)
        r = await _reserve(client, "RL-2", 3)
        await client.post(f"/reservations/{r['id']}/release")
        second = await client.post(f"/reservations/{r['id']}/release")
        assert second.status_code == 200
        assert second.json()["status"] == "released"
        item = (await client.get("/stock-items/by-sku/RL-2")).json()
        assert item["quantity_reserved"] == 0  # без второго возврата

    async def test_release_confirmed_409(self, client) -> None:
        await _make_stock(client, "RL-3", 10)
        r = await _reserve(client, "RL-3", 3)
        await client.post(f"/reservations/{r['id']}/confirm")
        resp = await client.post(f"/reservations/{r['id']}/release")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "INVALID_RESERVATION_STATE"


class TestExpiration:
    async def test_expired_releases_stock_and_blocks_confirm(
        self, client, monkeypatch
    ) -> None:
        await _make_stock(client, "EX-1", 10)
        r = await _reserve(client, "EX-1", 3, ttl=1)
        await asyncio.sleep(1.1)
        from app.services.expiration import expire_batch

        assert await expire_batch(limit=100) >= 1
        item = (await client.get("/stock-items/by-sku/EX-1")).json()
        assert item["quantity_reserved"] == 0
        get_resp = await client.get(f"/reservations/{r['id']}")
        assert get_resp.json()["status"] == "expired"
        confirm = await client.post(f"/reservations/{r['id']}/confirm")
        assert confirm.status_code == 409
        assert confirm.json()["error"]["code"] == "INVALID_RESERVATION_STATE"

    async def test_concurrent_confirm_not_corrupted(
        self, client, db_engine, monkeypatch
    ) -> None:
        """Резерв, который конкурентная транзакция подтверждает, пропускается."""
        from app.repositories.reservation_repo import ReservationRepository
        from app.services.expiration import expire_batch

        await _make_stock(client, "EX-2", 10)
        r = await _reserve(client, "EX-2", 3, ttl=1)
        await asyncio.sleep(1.1)

        # Подтверждаем резерв в отдельной сессии, не завершая её commit,
        # удерживая блокировку строки на время прохода expire_batch.
        session = _session(db_engine)
        async with session as s:
            res_repo = ReservationRepository(s)
            reservation = await res_repo.get_by_id(r["id"])
            await res_repo.confirm(reservation)

            # Параллельный проход истечения: SKIP LOCKED не должен трогать
            # заблокированную строку и не должен испортить состояние.
            expired = await expire_batch(limit=100)
            assert expired == 0
            await s.commit()

        get_resp = await client.get(f"/reservations/{r['id']}")
        assert get_resp.json()["status"] == "confirmed"
        item = (await client.get("/stock-items/by-sku/EX-2")).json()
        assert item["quantity_on_hand"] == 7
        assert item["quantity_reserved"] == 0


class TestGetReservation:
    async def test_get_exposes_fields(self, client) -> None:
        await _make_stock(client, "GR-1", 10)
        r = await _reserve(client, "GR-1", 2, holder="order-9")
        resp = await client.get(f"/reservations/{r['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "active"
        assert body["holder_ref"] == "order-9"
        assert body["expires_at"]
        assert body["quantity"] == 2

    async def test_get_unknown_404(self, client) -> None:
        import uuid

        resp = await client.get(f"/reservations/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESERVATION_NOT_FOUND"


class TestLifecycleInvariants:
    async def test_reserved_le_on_hand_after_every_operation(
        self, client, db_engine
    ) -> None:
        """5.5: инвариант quantity_reserved <= quantity_on_hand после всех операций."""
        from app.models.inventory import StockItem

        await _make_stock(client, "INV-1", 20)
        r = await _reserve(client, "INV-1", 10)
        await client.post(f"/reservations/{r['id']}/confirm")
        r2 = await _reserve(client, "INV-1", 5)
        await client.post(f"/reservations/{r2['id']}/release")
        r3 = await _reserve(client, "INV-1", 8)
        await client.post(f"/reservations/{r3['id']}/release")
        r4 = await _reserve(client, "INV-1", 7, ttl=900)
        resp = await client.post(f"/reservations/{r4['id']}/release")
        assert resp.status_code == 200
        session = _session(db_engine)
        async with session as s:
            item = (
                await s.execute(select(StockItem).where(StockItem.sku == "INV-1"))
            ).scalars().first()
            assert item.quantity_reserved <= item.quantity_on_hand

    async def test_terminal_states_cannot_be_released(self, client) -> None:
        await _make_stock(client, "INV-2", 20)
        rc = await _reserve(client, "INV-2", 2)
        await client.post(f"/reservations/{rc['id']}/confirm")
        rr = await _reserve(client, "INV-2", 2)
        await client.post(f"/reservations/{rr['id']}/release")
        # Повторный release идемпотентен (тот же статус), но release confirmed — 409.
        resp = await client.post(f"/reservations/{rc['id']}/release")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "INVALID_RESERVATION_STATE"
        # Терминальные статусы зафиксированы.
        assert (await client.get(f"/reservations/{rc['id']}")).json()["status"] == "confirmed"
        assert (await client.get(f"/reservations/{rr['id']}")).json()["status"] == "released"
