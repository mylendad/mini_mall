"""Фоновый релей outbox: PostgreSQL -> Elasticsearch.

Релей — asyncio-задача, стартует в ``lifespan`` и раз в ``outbox_poll_interval``
выполняет ``process_outbox``: читает пачку ``pending``-строк, для каждой
перечитывает авторитетное состояние продукта из БД и применяет операцию ES
(под protection ``relay_breaker``), затем помечает обработанной. Строки с
превышением ``outbox_max_attempts`` не удаляются (накапливаются как observable
``pending``), обработанные — чистятся по ретенции
``outbox_retention_seconds``; необработанные накапливаются и замеряются
логом/метриками.

Крэш-безопасность: на старте довольно — предыдущие незавершённые строки ещё
в ``pending`` и будут обработаны этим проходом.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app import elasticsearch as es
from app.config import settings
from app.database import async_session_maker
from app.metrics import catalog_sync_failures_total
from app.models.catalog import Product
from app.models.outbox import IndexOutbox
from app.services.breaker import BreakerOpenError, relay_breaker
from app.services.indexer import delete_product, index_product

logger = structlog.get_logger()

PROCESSING_BATCH = 200
_LAST_ERROR_LIMIT = 500


def _backoff_elapsed(row: IndexOutbox, now: datetime) -> bool:
    """Проверяет, истекла ли экспоненциальная задержка между попытками."""
    if row.attempt_count <= 1:
        return True
    base = settings.outbox_backoff_base
    delay = base * (2 ** (row.attempt_count - 1))
    return (now - row.created_at).total_seconds() >= delay


async def _apply_event(
    db: AsyncSession, envelope: dict[str, Any], breaker: Any
) -> None:
    """Перечитывает продукт из PG и применяет операцию ES (авторитетно).

    Payload — толстый снимок продукта (D4, Event-Carried State Transfer),
    но релей использует из него только ``id`` и никогда не доверяет состоянию
    снимка: источник истины — актуальная строка PostgreSQL.
    """
    event_type = envelope.get("event_type", "")
    payload = envelope.get("payload", {})
    product_id = uuid.UUID(payload.get("id") or payload.get("product_id"))

    if event_type == "product.deleted":
        await breaker.call(delete_product, es.es_client, product_id)
        return

    product = (
        await db.execute(
            select(Product)
            .options(joinedload(Product.category))
            .where(Product.id == product_id)
        )
    ).scalar_one_or_none()
    if product is None:
        # Продукт уже удалён из БД, а событие создания/обновления запоздало.
        await breaker.call(delete_product, es.es_client, product_id)
        return
    await breaker.call(index_product, es.es_client, product, product.category.name)


def _processed_cleanup_stmt(cutoff: datetime):
    """DELETE-выражение для обработанных строк старше ``cutoff``."""
    return delete(IndexOutbox).where(
        IndexOutbox.status == "processed",
        IndexOutbox.processed_at < cutoff,
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
        select(IndexOutbox)
        .where(IndexOutbox.status == "pending")
        .order_by(IndexOutbox.created_at)
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars())

    processed = 0
    failed = 0
    for row in rows:
        if row.attempt_count >= settings.outbox_max_attempts:
            continue
        if not _backoff_elapsed(row, now):
            continue
        try:
            await _apply_event(db, row.envelope, relay_breaker)
        except BreakerOpenError:
            catalog_sync_failures_total.labels(
                operation=row.envelope.get("event_type", "unknown")
            ).inc()
            failed += 1
            continue
        except Exception as exc:  # noqa: BLE001 - внешняя система, сбой логируем
            row.attempt_count += 1
            row.last_error = str(exc)[:_LAST_ERROR_LIMIT]
            catalog_sync_failures_total.labels(
                operation=row.envelope.get("event_type", "unknown")
            ).inc()
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

    await cleanup_outbox(db, now=now)
    await db.commit()
    return processed, failed


async def relay_job(stop_event: asyncio.Event) -> None:
    """Бесконечный цикл релея; останавливается установкой ``stop_event``."""
    logger.info("relay.started")
    try:
        while not stop_event.is_set():
            try:
                async with async_session_maker() as db:
                    processed, failed = await process_outbox(db)
                    if processed or failed:
                        logger.info("relay.tick", processed=processed, failed=failed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("relay.tick_failed", error=str(exc))
            await asyncio.sleep(settings.outbox_poll_interval)
    finally:
        logger.info("relay.stopped")
