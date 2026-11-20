"""Фоновое задание истечения резервов.

Asyncio-задача (стартует в ``lifespan``, интервал из настроек) раз в
``expiration_interval`` выбирает пачку ``active`` резервов с
``expires_at < now()`` (сравнение по часам БД) ``FOR UPDATE SKIP LOCKED``,
возвращает зарезервированный склад, помечает резерв ``expired`` и пишет
событие ``inventory.reservation.expired`` в outbox — всё одной транзакцией
на пачку. ``SKIP LOCKED`` пропускает резерв, который конкурентная
транзакция прямо сейчас подтверждает — он не портится.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from app.config import settings
from app.database import async_session_maker
from app.metrics import expiration_runs_total
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.stock_repo import StockRepository
from app.services.events import RESERVATION_EXPIRED, enqueue_event, reservation_envelope

logger = structlog.get_logger()


async def expire_batch(*, limit: int | None = None, now: datetime | None = None) -> int:
    """Истекает одну пачку просроченных резервов; возвращает число обработанных."""
    now = now or datetime.now(UTC)
    async with async_session_maker() as db:
        reservation_repo = ReservationRepository(db)
        stock_repo = StockRepository(db)
        reservations = await reservation_repo.select_expired(
            now=now, limit=limit or settings.expiration_batch_size
        )
        processed = 0
        for reservation in reservations:
            stock_item = await stock_repo.get_by_id(reservation.stock_item_id)
            if stock_item is None:
                continue
            expired = await reservation_repo.expire(reservation)
            if expired is None:
                # Склад уже не содержит резерв (гонка с confirm) — пропускаем.
                continue
            await enqueue_event(
                db,
                reservation_envelope(RESERVATION_EXPIRED, expired, stock_item),
            )
            processed += 1
        await db.commit()
    if processed:
        logger.info("expiration.processed", count=processed)
    return processed


async def expiration_job(stop_event: asyncio.Event) -> None:
    """Бесконечный цикл задания истечения; останавливается ``stop_event``."""
    logger.info("expiration.started", interval=settings.expiration_interval)
    try:
        while not stop_event.is_set():
            try:
                expiration_runs_total.inc()
                await expire_batch()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("expiration.tick_failed", error=str(exc))
            await asyncio.sleep(settings.expiration_interval)
    finally:
        logger.info("expiration.stopped")
