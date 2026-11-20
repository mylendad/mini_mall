"""Интеграционные тесты Kafka: потребитель команд, релей, outage (фазы 6-7)."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.usefixtures("db_engine", "kafka_bootstrap")


def _session(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)()


def _command_message(command: str, sku: str, qty: int, order: str) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "command": command,
        "order_id": order,
        "items": [{"sku": sku, "quantity": qty}],
        "saga_ref": "saga-kafka",
        "correlation_id": str(uuid.uuid4()),
    }


@pytest_asyncio.fixture
async def commands_topic(kafka_bootstrap):
    from aiokafka.admin import AIOKafkaAdminClient, NewTopic
    from aiokafka.errors import TopicAlreadyExistsError

    from app.config import settings

    admin = AIOKafkaAdminClient(bootstrap_servers=kafka_bootstrap)
    await admin.start()
    try:
        for name in (settings.commands_topic, settings.events_topic):
            try:
                await admin.create_topics(
                    [NewTopic(name, num_partitions=1, replication_factor=1)]
                )
            except TopicAlreadyExistsError:
                pass
    finally:
        await admin.close()
    return settings.commands_topic


async def _consume_events(kafka_bootstrap, topic, max_messages: int = 10, timeout: float = 15.0):
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=kafka_bootstrap,
        group_id=f"test-{uuid.uuid4()}",
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )
    # aiokafka не поддерживает consumer_timeout_ms: читаем через getone
    # с явным таймаутом на каждое сообщение.
    await asyncio.wait_for(consumer.start(), timeout)
    try:
        messages = []
        while len(messages) < max_messages:
            try:
                msg = await asyncio.wait_for(consumer.getone(), timeout=2.0)
            except TimeoutError:
                break
            if msg is None:
                break
            messages.append(msg.value)
        return messages
    finally:
        await asyncio.wait_for(consumer.stop(), 10.0)


class TestConsumer:
    @pytest_asyncio.fixture
    async def consumer_task(self, commands_topic):
        from app.services.consumer import consume_commands

        stop_event = asyncio.Event()
        task = asyncio.create_task(consume_commands(stop_event))
        await asyncio.sleep(2.0)  # дать rebalance завершиться
        yield task
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_reserve_confirm_release_commands_drive_state(
        self, client, consumer_task, commands_topic
    ) -> None:
        from aiokafka import AIOKafkaProducer

        resp = await client.post(
            "/stock-items", json={"sku": "KC-1", "quantity_on_hand": 50}
        )
        assert resp.status_code == 201

        producer = AIOKafkaProducer(
            bootstrap_servers=consumer_bootstrap(),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await producer.start()
        try:
            for command in ("reserve", "confirm"):
                await producer.send_and_wait(
                    commands_topic,
                    value=_command_message(command, "KC-1", 5, "order-kc1"),
                )
        finally:
            await producer.stop()

        # Ждём обработки обеих команд.
        for _ in range(40):
            item = (await client.get("/stock-items/by-sku/KC-1")).json()
            if item["quantity_on_hand"] == 45 and item["quantity_reserved"] == 0:
                break
            await asyncio.sleep(0.5)
        assert item["quantity_on_hand"] == 45
        assert item["quantity_reserved"] == 0

    async def test_redelivered_command_acked_without_side_effects(
        self, client, consumer_task, commands_topic
    ) -> None:
        from aiokafka import AIOKafkaProducer

        resp = await client.post(
            "/stock-items", json={"sku": "KC-2", "quantity_on_hand": 50}
        )
        assert resp.status_code == 201

        message = _command_message("reserve", "KC-2", 5, "order-kc2")
        producer = AIOKafkaProducer(
            bootstrap_servers=consumer_bootstrap(),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await producer.start()
        try:
            for _ in range(2):  # повторная доставка того же event_id
                await producer.send_and_wait(commands_topic, value=message)
        finally:
            await producer.stop()

        for _ in range(40):
            item = (await client.get("/stock-items/by-sku/KC-2")).json()
            if item["quantity_reserved"] == 5:
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(2.0)  # дать время обработать повторную доставку
        item = (await client.get("/stock-items/by-sku/KC-2")).json()
        assert item["quantity_reserved"] == 5  # без двойного резерва


def consumer_bootstrap():
    from app.config import settings

    return settings.kafka_bootstrap_servers


class TestRelay:
    async def test_outbox_rows_published_once_and_marked(
        self, client, db_engine, commands_topic
    ) -> None:
        from app import kafka
        from app.database import async_session_maker
        from app.services.events import RESERVED, build_envelope
        from app.services.relay import process_outbox

        resp = await client.post(
            "/stock-items", json={"sku": "RL-K1", "quantity_on_hand": 10}
        )
        assert resp.status_code == 201

        envelope = build_envelope(
            RESERVED, {"sku": "RL-K1", "quantity": 1}
        )
        async with async_session_maker() as db:
            from app.services.events import enqueue_event

            await enqueue_event(db, envelope)
            await db.commit()

        producer = kafka.create_producer()
        await producer.start()
        try:
            async with async_session_maker() as db:
                processed, failed = await process_outbox(db, producer)
        finally:
            await producer.stop()
        assert processed >= 1
        assert failed == 0

        from sqlalchemy import select as sa_select

        from app.models.outbox import InventoryOutbox

        async with async_session_maker() as db:
            row = (
                (
                    await db.execute(
                        sa_select(InventoryOutbox).where(
                            InventoryOutbox.event_id == envelope.event_id
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert row.status == "processed"

        events = await _consume_events(
            consumer_bootstrap(), _events_topic(), max_messages=100
        )
        matching = [
            e
            for e in events
            if e.get("event_type") == RESERVED
            and str(e.get("event_id")) == str(envelope.event_id)
        ]
        assert len(matching) == 1

        # Повторный проход не публикует снова (строка помечена processed).
        producer = kafka.create_producer()
        await producer.start()
        try:
            async with async_session_maker() as db:
                processed2, _ = await process_outbox(db, producer)
        finally:
            await producer.stop()
        assert processed2 == 0


def _events_topic():
    from app.config import settings

    return settings.events_topic


class TestOutageSemantics:
    async def test_api_succeeds_and_backlog_published_after_recovery(
        self, client, db_engine, commands_topic, monkeypatch
    ) -> None:
        """7.4: Kafka недоступна -> API работает, события ждут; восстановление -> релей догоняет."""
        from app import kafka
        from app.database import async_session_maker
        from app.services.relay import process_outbox

        # "Outage": producer-заглушка, у которой публикация всегда падает
        # (имитация недоступного брокера; start() против мёртвого брокера
        # просто бросил бы исключение до process_outbox).
        class _DeadProducer:
            async def send_and_wait(self, *args, **kwargs):
                raise ConnectionError("kafka is down")

        resp = await client.post(
            "/stock-items",
            json={"sku": "OUT-1", "quantity_on_hand": 10},
        )
        assert resp.status_code == 201  # синхронный путь работает

        async with async_session_maker() as db:
            processed, _failed = await process_outbox(db, _DeadProducer())
            from sqlalchemy import select as sa_select

            from app.models.outbox import InventoryOutbox

            rows = (
                (
                    await db.execute(
                        sa_select(InventoryOutbox).order_by(InventoryOutbox.id)
                    )
                )
                .scalars()
                .all()
            )
            stock_created = [
                r
                for r in rows
                if r.envelope.get("payload", {}).get("sku") == "OUT-1"
            ]
        assert processed == 0  # ни одна строка не опубликована
        assert stock_created
        assert stock_created[0].status == "pending"  # событие ждёт восстановления
        assert stock_created[0].last_error

        # Восстановление: настоящий брокер — релей публикует накопленное.
        producer = kafka.create_producer()
        await producer.start()
        try:
            async with async_session_maker() as db:
                processed, _ = await process_outbox(db, producer)
        finally:
            await producer.stop()
        assert processed >= 1

        events = await _consume_events(
            consumer_bootstrap(), _events_topic(), max_messages=100
        )
        assert any(
            e.get("payload", {}).get("sku") == "OUT-1" for e in events
        )

    async def test_poison_row_capped_and_does_not_block(
        self, client, db_engine, commands_topic, monkeypatch
    ) -> None:
        from app import kafka
        from app.config import settings
        from app.database import async_session_maker
        from app.models.outbox import InventoryOutbox
        from app.services.relay import process_outbox

        monkeypatch.setattr(settings, "outbox_max_attempts", 2)

        # Пачка: одна ядовитая строка + одна хорошая.
        bad = InventoryOutbox(
            event_id=uuid.uuid4(), envelope={"event_type": "broken"}
        )  # не проходит валидацию EventEnvelope
        good_envelope = build_envelope_safe()
        good = InventoryOutbox(
            event_id=good_envelope.event_id,
            envelope=good_envelope.model_dump(mode="json"),
        )
        async with async_session_maker() as db:
            db.add_all([bad, good])
            await db.commit()

        producer = kafka.create_producer()
        await producer.start()
        try:
            async with async_session_maker() as db:
                await process_outbox(db, producer)
            async with async_session_maker() as db:
                rows = (
                    (await db.execute(select(InventoryOutbox))).scalars().all()
                )
                by_id = {r.event_id: r for r in rows}
                assert by_id[bad.event_id].attempt_count == 1
                assert by_id[good.event_id].status == "processed"
            # Второй проход: плохая строка достигает max_attempts и остаётся
            # observable, другие строки обрабатываются дальше.
            async with async_session_maker() as db:
                await process_outbox(db, producer)
            async with async_session_maker() as db:
                rows = (
                    (await db.execute(select(InventoryOutbox))).scalars().all()
                )
                by_id = {r.event_id: r for r in rows}
                bad_row = by_id[bad.event_id]
                good_row = by_id[good.event_id]
                assert bad_row.attempt_count == settings.outbox_max_attempts
                assert bad_row.last_error
                assert bad_row.status == "pending"  # не удаляется, observable
                assert good_row.status == "processed"
        finally:
            await producer.stop()


def build_envelope_safe():
    from app.services.events import RESERVED, build_envelope

    return build_envelope(RESERVED, {"sku": "poison-good", "quantity": 1})


class TestLowStockEndToEnd:
    async def test_low_stock_event_flows_through_relay(
        self, client, db_engine, commands_topic
    ) -> None:
        """8.3: пересечение порога -> outbox -> релей -> Kafka."""
        from app import kafka
        from app.config import settings
        from app.database import async_session_maker
        from app.services.relay import process_outbox

        resp = await client.post(
            "/stock-items",
            json={"sku": "LSE-1", "quantity_on_hand": 15, "low_stock_threshold": 10},
        )
        assert resp.status_code == 201
        reserve = await client.post(
            "/reservations",
            json={"sku": "LSE-1", "quantity": 6, "holder_ref": "o", "ttl_seconds": 900},
        )
        assert reserve.status_code == 201

        producer = kafka.create_producer()
        await producer.start()
        try:
            async with async_session_maker() as db:
                await process_outbox(db, producer)
        finally:
            await producer.stop()

        events = await _consume_events(
            consumer_bootstrap(), settings.events_topic, max_messages=100
        )
        low = [
            e
            for e in events
            if e.get("event_type") == "inventory.low_stock"
            and e.get("payload", {}).get("sku") == "LSE-1"
        ]
        assert len(low) == 1
        envelope = low[0]
        assert envelope["producer"] == settings.app_name
        assert envelope["correlation_id"]
        assert envelope["payload"]["available_before"] == 15
        assert envelope["payload"]["available_after"] == 9
