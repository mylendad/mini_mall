"""Фоновый релей outbox: PostgreSQL -> Kafka.

Релей — asyncio-задача, стартует в ``lifespan`` и раз в ``outbox_poll_interval``
выполняет ``process_outbox``: читает пачку ``pending``-строк, публикует
конверты в событийный топик (под защитой ``relay_breaker``), помечает
обработанными. Строки с превышением ``outbox_max_attempts`` не удаляются
(остаются observable ``pending`` с ``last_error``); обработанные чистятся
по ретенции ``outbox_retention_seconds``. Kafka недоступна -> публикация
просто откладывается, синхронный путь не страдает.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from aiokafka import AIOKafkaProducer
from common.events import EventEnvelope
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import kafka
from app.config import settings
from app.database import async_session_maker
from app.metrics import outbox_failures_total, outbox_pending
from app.models.outbox import InventoryOutbox
from app.services.breaker import relay_breaker

logger = structlog.get_logger()

PROCESSING_BATCH = 200
_LAST_ERROR_LIMIT = 500


def _backoff_elapsed(row: InventoryOutbox, now: datetime) -> bool:
    """Проверяет, истекла ли экспоненциальная задержка между попытками."""
    if row.attempt_count <= 1:
        return True
    base = settings.outbox_backoff_base
    delay = base * (2 ** (row.attempt_count - 1))
    return (now - row.created_at).total_seconds() >= delay


def _processed_cleanup_stmt(cutoff: datetime):
    """DELETE-выражение для обработанных строк старше ``cutoff``."""
    return delete(InventoryOutbox).where(
        InventoryOutbox.status == "processed",
        InventoryOutbox.processed_at < cutoff,
    )


async def cleanup_outbox(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    retention_seconds: int | None = None,
) -> None:
    """Удаляет обработанные строки outbox старше ретенции (защита от роста).

    Вызывается раз за проход релея; ``retention_seconds<=0`` отключает чистку.
    """
    now = now or datetime.now(UTC)
    retention = (
        settings.outbox_retention_seconds
        if retention_seconds is None
        else retention_seconds
    )
    if retention <= 0:
        return
    cutoff = now - timedelta(seconds=retention)
    await db.execute(_processed_cleanup_stmt(cutoff))


async def process_outbox(
    db: AsyncSession,
    producer: AIOKafkaProducer,
    *,
    limit: int = PROCESSING_BATCH,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Обрабатывает пачку ``pending``-строк outbox.

    Возвращает:
        Кортеж ``(обработано, с ошибками)``.
    """
    now = now or datetime.now(UTC)
    stmt = (
        select(InventoryOutbox)
        .where(InventoryOutbox.status == "pending")
        .order_by(InventoryOutbox.created_at)
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars())

    processed = 0
    failed = 0
    poisoned = 0
    for row in rows:
        if row.attempt_count >= settings.outbox_max_attempts:
            poisoned += 1
            continue
        if not _backoff_elapsed(row, now):
            continue
        try:
            envelope = EventEnvelope.model_validate(row.envelope)
            await relay_breaker.call(kafka.publish_envelope, producer, envelope)
        except Exception as exc:  # noqa: BLE001 - внешняя система, сбой логируем
            row.attempt_count += 1
            row.last_error = str(exc)[:_LAST_ERROR_LIMIT]
            if row.attempt_count >= settings.outbox_max_attempts:
                outbox_failures_total.inc()
            logger.warning(
                "outbox.process_failed",
                row_id=row.id,
                event_id=str(row.event_id),
                error=str(exc),
            )
            failed += 1
            continue
        row.status = "processed"
        row.processed_at = datetime.now(UTC)
        processed += 1

    pending_count = (
        await db.execute(
            select(func.count())
            .select_from(InventoryOutbox)
            .where(InventoryOutbox.status == "pending")
        )
    ).scalar_one()
    outbox_pending.set(pending_count)

    await cleanup_outbox(db, now=now)
    await db.commit()
    if poisoned:
        logger.warning("outbox.poisoned_rows", count=poisoned)
    return processed, failed


async def relay_job(stop_event: asyncio.Event) -> None:
    """Бесконечный цикл релея; останавливается установкой ``stop_event``."""
    logger.info("relay.started")
    producer = kafka.create_producer()
    await producer.start()
    try:
        while not stop_event.is_set():
            try:
                async with async_session_maker() as db:
                    processed, failed = await process_outbox(db, producer)
                    if processed or failed:
                        logger.info("relay.tick", processed=processed, failed=failed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("relay.tick_failed", error=str(exc))
            await asyncio.sleep(settings.outbox_poll_interval)
    finally:
        try:
            await producer.stop()
        except Exception as exc:  # noqa: BLE001 - остановка релея не должна падать
            logger.warning("relay.stop_failed", error=str(exc))
        logger.info("relay.stopped")
