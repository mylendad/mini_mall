"""Обработчик команд саги (checkout-участие инвентаря).

Seam между Kafka-потребителем и теми же репозиторными операциями, что
использует HTTP API. Обработка идемпотентна по ``event_id``: строка
``processed_commands`` вставляется в той же транзакции, что и изменение
состояния; уникальное нарушение при повторной доставке — команда
считается уже обработанной и просто аккается. Исходы команд
(``inventory.reserved``/``inventory.reservation_failed``/``inventory.confirmed``/
``inventory.released``) пишутся в outbox в той же транзакции.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.metrics import reservations_total
from app.models.inventory import ProcessedCommand, Reservation
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.stock_repo import StockRepository
from app.schemas.saga import SagaCommand
from app.services.events import (
    CONFIRMED,
    RELEASED,
    RESERVATION_FAILED,
    RESERVED,
    build_envelope,
    enqueue_event,
    reservation_envelope,
)

logger = structlog.get_logger()


def _expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(
        seconds=settings.reservation_default_ttl_seconds
    )


class SagaCommandHandler:
    """Обрабатывает команды саги (reserve/confirm/release).

    Параметры:
        db: Асинхронная сессия SQLAlchemy (одна на команду).
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.reservation_repo = ReservationRepository(db)
        self.stock_repo = StockRepository(db)

    async def handle(self, event_id: uuid.UUID, command: SagaCommand) -> bool:
        """Обрабатывает команду; возвращает ``True`` — можно акать offset.

        Повторная доставка (уникальный ``event_id``) возвращает ``True``
        без повторной обработки.
        """
        self.db.add(ProcessedCommand(event_id=event_id))
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            logger.info("saga.command_duplicate", event_id=str(event_id))
            return True

        if command.command == "reserve":
            await self._reserve(command)
        elif command.command == "confirm":
            await self._confirm(command)
        else:
            await self._release(command)
        await self.db.commit()
        return True

    async def _reserve(self, command: SagaCommand) -> None:
        """Reserve: по одному резерву на (order, sku); неудача — ``reservation_failed``."""
        for item in command.items:
            stock_item = await self.stock_repo.get_by_sku(item.sku)
            if stock_item is None:
                await self._failed(command, item.sku, "stock item not found")
                continue
            reservation = await self.reservation_repo.reserve(
                stock_item_id=stock_item.id,
                quantity=item.quantity,
                holder_ref=command.order_id,
                idempotency_key=None,
                expires_at=_expires_at(),
            )
            if reservation is None:
                reservations_total.labels(outcome="insufficient").inc()
                await self.db.rollback()
                await self._failed(command, item.sku, "insufficient stock")
                continue
            await self.db.refresh(stock_item)
            await enqueue_event(
                self.db,
                reservation_envelope(
                    RESERVED,
                    reservation,
                    stock_item,
                    correlation_id=command.correlation_id,
                ),
            )
            reservations_total.labels(outcome="reserved").inc()

    async def _confirm(self, command: SagaCommand) -> None:
        """Confirm: подтверждает активные резервы заказа (idемпотентно)."""
        for item in command.items:
            reservation = await self.reservation_repo.get_by_holder_and_sku(
                command.order_id, item.sku
            )
            if reservation is None:
                await self._failed(command, item.sku, "no reservation for order")
                continue
            await self._transition(
                command, reservation, "confirm", item.sku
            )

    async def _release(self, command: SagaCommand) -> None:
        """Release: компенсация; резерв, который уже истёк, — идемпотентный успех."""
        for item in command.items:
            reservation = await self.reservation_repo.get_by_holder_and_sku(
                command.order_id, item.sku
            )
            if reservation is None:
                await self._failed(command, item.sku, "no reservation for order")
                continue
            if reservation.status == "expired":
                # Компенсация уже не нужна: склад уже возвращён заданием
                # истечения. Идемпотентный успех — публикуем ``released``.
                stock_item = await self.stock_repo.get_by_id(
                    reservation.stock_item_id
                )
                if stock_item is not None:
                    await enqueue_event(
                        self.db,
                        reservation_envelope(
                            RELEASED,
                            reservation,
                            stock_item,
                            correlation_id=command.correlation_id,
                        ),
                    )
                continue
            await self._transition(
                command, reservation, "release", item.sku
            )

    async def _transition(
        self,
        command: SagaCommand,
        reservation: Reservation,
        operation: str,
        sku: str,
    ) -> None:
        """Confirm/release одного резерва с публикацией исхода (той же транзакцией).

        Повторное применение (уже confirmed/released) — идемпотентный успех:
        исход публикуется без второго изменения состояния.
        """
        stock_item = await self.stock_repo.get_by_id(reservation.stock_item_id)
        if stock_item is None:
            await self._failed(command, sku, "stock item not found")
            return
        already_done = (
            operation == "confirm" and reservation.status == "confirmed"
        ) or (operation == "release" and reservation.status == "released")
        if not already_done and reservation.status != "active":
            reservations_total.labels(outcome="insufficient").inc()
            await self.db.rollback()
            await self._failed(
                command, sku, f"reservation in state {reservation.status}"
            )
            return
        if already_done:
            await enqueue_event(
                self.db,
                reservation_envelope(
                    CONFIRMED if operation == "confirm" else RELEASED,
                    reservation,
                    stock_item,
                    correlation_id=command.correlation_id,
                ),
            )
            return
        updated = (
            await self.reservation_repo.confirm(reservation)
            if operation == "confirm"
            else await self.reservation_repo.release(reservation)
        )
        if updated is None:
            reservations_total.labels(outcome="insufficient").inc()
            await self.db.rollback()
            await self._failed(command, sku, "conditional update failed")
            return
        await enqueue_event(
            self.db,
            reservation_envelope(
                CONFIRMED if operation == "confirm" else RELEASED,
                updated,
                stock_item,
                correlation_id=command.correlation_id,
            ),
        )
        reservations_total.labels(
            outcome="confirmed" if operation == "confirm" else "released"
        ).inc()

    async def _failed(
        self, command: SagaCommand, sku: str, reason: str
    ) -> None:
        """Публикует ``inventory.reservation_failed`` (в текущей транзакции)."""
        payload: dict = {
            "order_id": command.order_id,
            "sku": sku,
            "reason": reason,
        }
        if command.saga_ref:
            payload["saga_ref"] = command.saga_ref
        await enqueue_event(
            self.db,
            build_envelope(RESERVATION_FAILED, payload, correlation_id=command.correlation_id),
        )
