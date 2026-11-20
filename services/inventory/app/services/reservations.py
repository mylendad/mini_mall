"""Сервис резервов: резерв, confirm, release (транзакционные границы).

Все изменения состояния — атомарные условные UPDATE в репозитории;
события (``inventory.reserved``/``inventory.confirmed``/``inventory.released``)
ставятся в outbox в той же транзакции. Идемпотентные повторения уже
применённых операций возвращают текущее состояние без второго изменения.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from common.errors import ErrorCode, error_detail
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import IntegrityErrorMapper
from app.metrics import reservations_total
from app.models.inventory import Reservation
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.stock_repo import StockRepository
from app.services.events import (
    CONFIRMED,
    RELEASED,
    RESERVED,
    enqueue_event,
    is_low_stock_crossing,
    low_stock_envelope,
    reservation_envelope,
)


class ReservationService:
    """Жизненный цикл резервов.

    Параметры:
        db: Асинхронная сессия SQLAlchemy.
        default_ttl_seconds: TTL по умолчанию, секунды (из настроек).
    """

    def __init__(self, db: AsyncSession, default_ttl_seconds: int):
        self.db = db
        self.repo = ReservationRepository(db)
        self.stock_repo = StockRepository(db)
        self.mapper = IntegrityErrorMapper()
        self.default_ttl_seconds = default_ttl_seconds

    async def reserve(
        self,
        *,
        sku: str,
        quantity: int,
        holder_ref: str,
        ttl_seconds: int | None = None,
        idempotency_key: str | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> Reservation:
        """Создаёт резерв одним атомарным UPDATE (без перепродажи).

        Исключения:
            HTTPException(404): ``STOCK_ITEM_NOT_FOUND``.
            HTTPException(409): ``INSUFFICIENT_STOCK`` (0 строк совпало).
        Повтор с тем же ``idempotency_key`` возвращает исходный резерв
        (второго резерва не создаётся).
        """
        existing = (
            await self.repo.get_by_idempotency_key(idempotency_key)
            if idempotency_key
            else None
        )
        if existing is not None:
            return existing

        item = await self.stock_repo.get_by_sku(sku)
        if item is None:
            reservations_total.labels(outcome="insufficient").inc()
            raise HTTPException(
                status_code=ErrorCode.STOCK_ITEM_NOT_FOUND.status_code,
                detail=error_detail(ErrorCode.STOCK_ITEM_NOT_FOUND),
            )
        available_before = item.available
        ttl = ttl_seconds or self.default_ttl_seconds
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        try:
            reservation = await self.repo.reserve(
                stock_item_id=item.id,
                quantity=quantity,
                holder_ref=holder_ref,
                idempotency_key=idempotency_key,
                expires_at=expires_at,
            )
        except IntegrityError as exc:
            await self.db.rollback()
            mapped = self.mapper.reservation_write(exc)
            if mapped is not None:
                # Конкурентный дубль идемпотентного ключа: возвращаем исходный резерв.
                existing = await self.repo.get_by_idempotency_key(idempotency_key or "")
                if existing is not None:
                    return existing
                raise HTTPException(
                    status_code=ErrorCode(mapped["code"]).status_code,
                    detail=mapped,
                )
            raise
        if reservation is None:
            reservations_total.labels(outcome="insufficient").inc()
            await self.db.rollback()
            raise HTTPException(
                status_code=ErrorCode.INSUFFICIENT_STOCK.status_code,
                detail=error_detail(ErrorCode.INSUFFICIENT_STOCK),
            )
        await self.db.refresh(item)
        await enqueue_event(
            self.db,
            reservation_envelope(RESERVED, reservation, item, correlation_id=correlation_id),
        )
        if is_low_stock_crossing(
            available_before=available_before,
            available_after=item.available,
            threshold=item.low_stock_threshold,
        ):
            await enqueue_event(
                self.db,
                low_stock_envelope(
                    item,
                    available_before=available_before,
                    available_after=item.available,
                    correlation_id=correlation_id,
                ),
            )
        await self.db.commit()
        reservations_total.labels(outcome="reserved").inc()
        return reservation

    async def get(self, reservation_id: uuid.UUID) -> Reservation:
        """Возвращает резерв по id или ``404 RESERVATION_NOT_FOUND``."""
        reservation = await self.repo.get_by_id(reservation_id)
        if reservation is None:
            raise HTTPException(
                status_code=ErrorCode.RESERVATION_NOT_FOUND.status_code,
                detail=error_detail(ErrorCode.RESERVATION_NOT_FOUND),
            )
        return reservation

    async def confirm(
        self,
        reservation_id: uuid.UUID,
        *,
        correlation_id: uuid.UUID | None = None,
    ) -> Reservation:
        """Подтверждает резерв: списывает on_hand и reserved, статус ``confirmed``.

        Исключения:
            HTTPException(404): резерв не найден.
            HTTPException(409): ``INVALID_RESERVATION_STATE`` (не active) или
                ``INSUFFICIENT_STOCK`` (склад ушёл ниже величины резерва).
        Повторный confirm возвращает подтверждённый резерв без второго списания.
        """
        reservation = await self.get(reservation_id)
        item = await self.stock_repo.get_by_id(reservation.stock_item_id)
        if item is None:
            await self.db.rollback()
            raise HTTPException(
                status_code=ErrorCode.INTERNAL_ERROR.status_code,
                detail=error_detail(ErrorCode.INTERNAL_ERROR),
            )
        if reservation.status == "confirmed":
            await self.db.rollback()
            return await self.repo.get_by_id(reservation_id)
        if reservation.status != "active":
            await self.db.rollback()
            raise HTTPException(
                status_code=ErrorCode.INVALID_RESERVATION_STATE.status_code,
                detail=error_detail(ErrorCode.INVALID_RESERVATION_STATE),
            )
        available_before = item.available
        confirmed = await self.repo.confirm(reservation)
        if confirmed is None:
            await self.db.rollback()
            reservations_total.labels(outcome="insufficient").inc()
            raise HTTPException(
                status_code=ErrorCode.INSUFFICIENT_STOCK.status_code,
                detail=error_detail(ErrorCode.INSUFFICIENT_STOCK),
            )
        # Confirm уменьшает on_hand и reserved поровну — доступность не меняется,
        # поэтому пересечение порога low-stock здесь невозможно; проверка
        # выполняется на всякий случай (единый контракт для всех списаний).
        if is_low_stock_crossing(
            available_before=available_before,
            available_after=item.available,
            threshold=item.low_stock_threshold,
        ):
            await enqueue_event(
                self.db,
                low_stock_envelope(
                    item,
                    available_before=available_before,
                    available_after=item.available,
                    correlation_id=correlation_id,
                ),
            )
        await enqueue_event(
            self.db,
            reservation_envelope(CONFIRMED, confirmed, item, correlation_id=correlation_id),
        )
        await self.db.commit()
        reservations_total.labels(outcome="confirmed").inc()
        return confirmed

    async def release(
        self,
        reservation_id: uuid.UUID,
        *,
        correlation_id: uuid.UUID | None = None,
    ) -> Reservation:
        """Освобождает резерв: возвращает reserved, статус ``released``.

        Исключения:
            HTTPException(404): резерв не найден.
            HTTPException(409): ``INVALID_RESERVATION_STATE`` (уже
                confirmed/released/expired).
        Повторный release возвращает освобождённый резерв без второго возврата.
        """
        reservation = await self.get(reservation_id)
        item = await self.stock_repo.get_by_id(reservation.stock_item_id)
        if item is None:
            await self.db.rollback()
            raise HTTPException(
                status_code=ErrorCode.INTERNAL_ERROR.status_code,
                detail=error_detail(ErrorCode.INTERNAL_ERROR),
            )
        if reservation.status == "released":
            await self.db.rollback()
            return await self.repo.get_by_id(reservation_id)
        if reservation.status != "active":
            await self.db.rollback()
            raise HTTPException(
                status_code=ErrorCode.INVALID_RESERVATION_STATE.status_code,
                detail=error_detail(ErrorCode.INVALID_RESERVATION_STATE),
            )
        released = await self.repo.release(reservation)
        if released is None:
            await self.db.rollback()
            raise HTTPException(
                status_code=ErrorCode.INVALID_RESERVATION_STATE.status_code,
                detail=error_detail(ErrorCode.INVALID_RESERVATION_STATE),
            )
        await enqueue_event(
            self.db,
            reservation_envelope(RELEASED, released, item, correlation_id=correlation_id),
        )
        await self.db.commit()
        reservations_total.labels(outcome="released").inc()
        return released
