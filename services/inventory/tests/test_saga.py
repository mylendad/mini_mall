"""Интеграционные тесты контракта саги: идемпотентность команд и outbox (фаза 6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.usefixtures("db_engine")


def _session(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)()


def _cmd(command: str, sku: str, qty: int, order: str = "order-1") -> dict:
    return {
        "command": command,
        "order_id": order,
        "items": [{"sku": sku, "quantity": qty}],
        "saga_ref": "saga-1",
        "correlation_id": str(uuid.uuid4()),
    }


async def _make_stock(client, sku, on_hand):
    resp = await client.post(
        "/stock-items", json={"sku": sku, "quantity_on_hand": on_hand}
    )
    assert resp.status_code == 201


async def _outbox_types(db_engine, sku: str | None = None) -> list[dict]:
    from app.models.outbox import InventoryOutbox

    session = _session(db_engine)
    async with session as s:
        rows = (
            (await s.execute(select(InventoryOutbox).order_by(InventoryOutbox.id)))
            .scalars()
            .all()
        )
        out = [
            {
                "event_id": str(r.event_id),
                "event_type": r.envelope["event_type"],
                "correlation_id": r.envelope.get("correlation_id"),
                "payload": r.envelope.get("payload") or {},
                "status": r.status,
            }
            for r in rows
        ]
    if sku is not None:
        out = [o for o in out if o["payload"].get("sku") == sku]
    return out


class TestMigrations:
    async def test_all_tables_exist(self, db_engine) -> None:
        """Все четыре таблицы созданы миграциями (up сделан в conftest)."""
        from sqlalchemy import text

        async with db_engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' ORDER BY table_name"
                )
            )
            tables = {r[0] for r in result}
        assert {
            "stock_items",
            "reservations",
            "processed_commands",
            "inventory_outbox",
        } <= tables


class TestSagaReserve:
    async def test_reserve_command_creates_reservation_and_outbox(
        self, client, db_engine
    ) -> None:
        from app.schemas.saga import parse_command
        from app.services.saga import SagaCommandHandler

        await _make_stock(client, "SG-1", 100)
        command = parse_command(_cmd("reserve", "SG-1", 10))
        session = _session(db_engine)
        async with session as s:
            assert await SagaCommandHandler(s).handle(uuid.uuid4(), command)
        item = (await client.get("/stock-items/by-sku/SG-1")).json()
        assert item["quantity_reserved"] == 10

        outbox = await _outbox_types(db_engine, "SG-1")
        reserved = [o for o in outbox if o["event_type"] == "inventory.reserved"]
        assert len(reserved) == 1
        assert str(reserved[0]["correlation_id"]) == str(command.correlation_id)
        assert reserved[0]["payload"]["sku"] == "SG-1"
        assert reserved[0]["payload"]["quantity"] == 10

    async def test_reserve_insufficient_publishes_failure(
        self, client, db_engine
    ) -> None:
        from app.schemas.saga import parse_command
        from app.services.saga import SagaCommandHandler

        await _make_stock(client, "SG-2", 5)
        command = parse_command(_cmd("reserve", "SG-2", 10))
        session = _session(db_engine)
        async with session as s:
            await SagaCommandHandler(s).handle(uuid.uuid4(), command)
        outbox = await _outbox_types(db_engine, "SG-2")
        failed = [
            o for o in outbox if o["event_type"] == "inventory.reservation_failed"
        ]
        assert len(failed) == 1
        assert failed[0]["payload"]["reason"] == "insufficient stock"
        item = (await client.get("/stock-items/by-sku/SG-2")).json()
        assert item["quantity_reserved"] == 0


class TestSagaIdempotency:
    async def test_duplicate_event_id_acked_without_side_effects(
        self, client, db_engine
    ) -> None:
        from app.schemas.saga import parse_command
        from app.services.saga import SagaCommandHandler

        await _make_stock(client, "SG-3", 100)
        command = parse_command(_cmd("reserve", "SG-3", 10))
        event_id = uuid.uuid4()
        session = _session(db_engine)
        async with session as s:
            assert await SagaCommandHandler(s).handle(event_id, command)
        async with _session(db_engine) as s2:
            assert await SagaCommandHandler(s2).handle(event_id, command)
        item = (await client.get("/stock-items/by-sku/SG-3")).json()
        assert item["quantity_reserved"] == 10  # без двойного резерва
        outbox = await _outbox_types(db_engine, "SG-3")
        assert len([o for o in outbox if o["event_type"] == "inventory.reserved"]) == 1

    async def test_expired_compensation_is_idempotent_success(
        self, client, db_engine
    ) -> None:
        from app.schemas.saga import parse_command
        from app.services.expiration import expire_batch
        from app.services.saga import SagaCommandHandler

        await _make_stock(client, "SG-4", 50)
        reserve_cmd = parse_command(_cmd("reserve", "SG-4", 10))
        async with _session(db_engine) as s:
            await SagaCommandHandler(s).handle(uuid.uuid4(), reserve_cmd)
        # Резерв TTL по умолчанию ещё не истёк — форсируем истечение напрямую:
        session = _session(db_engine)
        async with session as s:
            from app.models.inventory import Reservation

            rows = (await s.execute(select(Reservation))).scalars().all()
            for r in rows:
                await s.execute(
                    update_expires_at(r, seconds_ago=1)
                )
            await s.commit()
        async with _session(db_engine) as s:
            await expire_batch(limit=100)
        release_cmd = parse_command(_cmd("release", "SG-4", 10))
        async with _session(db_engine) as s:
            assert await SagaCommandHandler(s).handle(uuid.uuid4(), release_cmd)
        outbox = await _outbox_types(db_engine, "SG-4")
        released = [o for o in outbox if o["event_type"] == "inventory.released"]
        assert len(released) == 1  # идемпотентный успех: склад уже возвращён
        item = (await client.get("/stock-items/by-sku/SG-4")).json()
        assert item["quantity_reserved"] == 0
        assert item["quantity_on_hand"] == 50  # не списан дважды


def update_expires_at(reservation, seconds_ago: int):
    from sqlalchemy import update

    from app.models.inventory import Reservation

    return (
        update(Reservation)
        .where(Reservation.id == reservation.id)
        .values(
            expires_at=datetime.now(UTC) - timedelta(seconds=seconds_ago),
        )
    )


class TestSagaConfirmRelease:
    async def test_confirm_command_full_flow(self, client, db_engine) -> None:
        from app.schemas.saga import parse_command
        from app.services.saga import SagaCommandHandler

        await _make_stock(client, "SG-5", 30)
        order = "order-sg5"
        session = _session(db_engine)
        async with session as s:
            await SagaCommandHandler(s).handle(
                uuid.uuid4(), parse_command(_cmd("reserve", "SG-5", 7, order))
            )
        async with _session(db_engine) as s:
            await SagaCommandHandler(s).handle(
                uuid.uuid4(), parse_command(_cmd("confirm", "SG-5", 7, order))
            )
        item = (await client.get("/stock-items/by-sku/SG-5")).json()
        assert item["quantity_on_hand"] == 23
        assert item["quantity_reserved"] == 0
        outbox = await _outbox_types(db_engine, "SG-5")
        assert any(o["event_type"] == "inventory.confirmed" for o in outbox)

    async def test_release_command_compensation(self, client, db_engine) -> None:
        from app.schemas.saga import parse_command
        from app.services.saga import SagaCommandHandler

        await _make_stock(client, "SG-6", 30)
        order = "order-sg6"
        async with _session(db_engine) as s:
            await SagaCommandHandler(s).handle(
                uuid.uuid4(), parse_command(_cmd("reserve", "SG-6", 7, order))
            )
        async with _session(db_engine) as s:
            await SagaCommandHandler(s).handle(
                uuid.uuid4(), parse_command(_cmd("release", "SG-6", 7, order))
            )
        item = (await client.get("/stock-items/by-sku/SG-6")).json()
        assert item["quantity_reserved"] == 0
        assert item["quantity_on_hand"] == 30
        outbox = await _outbox_types(db_engine, "SG-6")
        assert any(o["event_type"] == "inventory.released" for o in outbox)

    async def test_unique_event_ids_in_outbox(self, client, db_engine) -> None:
        from app.schemas.saga import parse_command
        from app.services.saga import SagaCommandHandler

        await _make_stock(client, "SG-7", 100)
        async with _session(db_engine) as s:
            await SagaCommandHandler(s).handle(
                uuid.uuid4(), parse_command(_cmd("reserve", "SG-7", 1))
            )
        async with _session(db_engine) as s:
            await SagaCommandHandler(s).handle(
                uuid.uuid4(), parse_command(_cmd("confirm", "SG-7", 1, "order-1"))
            )
        outbox = await _outbox_types(db_engine, "SG-7")
        event_ids = [o["event_id"] for o in outbox]
        assert len(event_ids) == len(set(event_ids))
