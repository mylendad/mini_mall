"""Постановка событий инвентаря в outbox-очередь.

Запись строки :class:`~app.models.outbox.InventoryOutbox` выполняется в той
же транзакции, что и изменение состояния склада, поэтому откат транзакции
гарантированно не оставляет «фантомных» событий. Все конверты — версии
:class:`common.events.EventEnvelope` с ``producer: inventory-service`` и
пропагируемым ``correlation_id``.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from common.events import EventEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.inventory import Reservation, StockItem
from app.models.outbox import InventoryOutbox

logger = structlog.get_logger()

RESERVED = "inventory.reserved"
RESERVATION_FAILED = "inventory.reservation_failed"
CONFIRMED = "inventory.confirmed"
RELEASED = "inventory.released"
RESERVATION_EXPIRED = "inventory.reservation.expired"
STOCK_ADJUSTED = "inventory.stock.adjusted"
STOCK_ITEM_CREATED = "inventory.stock_item.created"
THRESHOLD_UPDATED = "inventory.threshold.updated"
LOW_STOCK = "inventory.low_stock"

EVENT_VERSION = 1


def _current_correlation_id() -> uuid.UUID | None:
    """Возвращает ``correlation_id`` из контекста structlog, если он задан."""
    raw = structlog.contextvars.get_contextvars().get("correlation_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def build_envelope(
    event_type: str,
    payload: dict[str, Any],
    *,
    correlation_id: uuid.UUID | None = None,
) -> EventEnvelope:
    """Собирает конверт события инвентаря (``producer: inventory-service``)."""
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type=event_type,
        event_version=EVENT_VERSION,
        producer=settings.app_name,
        correlation_id=correlation_id or _current_correlation_id() or uuid.uuid4(),
        payload=payload,
    )


def _stock_item_payload(item: StockItem) -> dict[str, Any]:
    """Снимок складской позиции для payload событий."""
    return {
        "id": str(item.id),
        "sku": item.sku,
        "catalog_product_id": (
            str(item.catalog_product_id) if item.catalog_product_id else None
        ),
        "quantity_on_hand": item.quantity_on_hand,
        "quantity_reserved": item.quantity_reserved,
        "available": item.available,
        "low_stock_threshold": item.low_stock_threshold,
    }


def _reservation_payload(reservation: Reservation) -> dict[str, Any]:
    """Снимок резерва для payload событий."""
    return {
        "id": str(reservation.id),
        "stock_item_id": str(reservation.stock_item_id),
        "quantity": reservation.quantity,
        "status": reservation.status,
        "holder_ref": reservation.holder_ref,
        "expires_at": reservation.expires_at.isoformat(),
    }


def stock_item_envelope(
    event_type: str,
    item: StockItem,
    *,
    extra: dict[str, Any] | None = None,
    correlation_id: uuid.UUID | None = None,
) -> EventEnvelope:
    """Конверт события складской позиции (создание/корректировка/порог)."""
    payload = _stock_item_payload(item)
    if extra:
        payload.update(extra)
    return build_envelope(event_type, payload, correlation_id=correlation_id)


def reservation_envelope(
    event_type: str,
    reservation: Reservation,
    item: StockItem,
    *,
    extra: dict[str, Any] | None = None,
    correlation_id: uuid.UUID | None = None,
) -> EventEnvelope:
    """Конверт события резерва (создание/подтверждение/освобождение/истечение)."""
    payload = {**_reservation_payload(reservation), "sku": item.sku}
    if extra:
        payload.update(extra)
    return build_envelope(event_type, payload, correlation_id=correlation_id)


def low_stock_envelope(
    item: StockItem,
    *,
    available_before: int,
    available_after: int,
    correlation_id: uuid.UUID | None = None,
) -> EventEnvelope:
    """Конверт события ``inventory.low_stock`` (пересечение порога сверху вниз)."""
    payload = _stock_item_payload(item)
    payload["available_before"] = available_before
    payload["available_after"] = available_after
    return build_envelope(LOW_STOCK, payload, correlation_id=correlation_id)


def is_low_stock_crossing(
    *, available_before: int, available_after: int, threshold: int
) -> bool:
    """Stateless-проверка пересечения порога low-stock сверху вниз.

    Возвращает ``True`` тогда и только тогда, когда доступность перешла
    порог вниз: ``available_before >= threshold > available_after``.
    Порог ``0`` отключает оповещения. Не хранит состояния —
    «перезарядка» происходит сама, когда доступность поднимается
    обратно до порога или выше.
    """
    if threshold <= 0:
        return False
    return available_before >= threshold > available_after


async def enqueue_event(
    db: AsyncSession, envelope: EventEnvelope
) -> InventoryOutbox:
    """Вставляет строку outbox в текущую транзакцию (без commit)."""
    row = InventoryOutbox(
        event_id=envelope.event_id, envelope=envelope.model_dump(mode="json")
    )
    db.add(row)
    await db.flush()
    return row
