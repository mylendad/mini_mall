"""Постановка событий синхронизации в outbox-очередь каталога.

Запись строки :class:`~app.models.outbox.IndexOutbox` выполняется в той же
транзакции, что и изменение продукта, поэтому откат продуктовой транзакции
гарантированно не оставляет «фантомных» событий индексации.

События — публичные доменные события (Event-Carried State Transfer): payload
содержит полный снимок продукта (``ProductResponse``), а не внутреннюю команду
синхронизации. Это даёт будущему Kafka-паблишеру транслировать outbox внешним
потребителям без изменений bounded-контекста. Фоновый релей по-прежнему
доверяет только ``id`` из payload и перечитывает авторитетное состояние из
PostgreSQL (D4: PG = source of truth).
"""

from __future__ import annotations

import uuid

import structlog
from common.events import EventEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.outbox import IndexOutbox
from app.schemas.catalog import ProductResponse

logger = structlog.get_logger()

PRODUCT_CREATED = "product.created"
PRODUCT_UPDATED = "product.updated"
PRODUCT_DELETED = "product.deleted"

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
    event_type: str, product: Product, correlation_id: uuid.UUID | None = None
) -> EventEnvelope:
    """Собирает конверт pub-события с толстым payload по D4.

    ``payload`` — полный снимок продукта (``ProductResponse``), сериализованный
    в JSON. Релей игнорирует это состояние и использует только ``payload["id"]``,
    перечитывая актуальную строку из PostgreSQL перед индексацией.
    """
    payload = ProductResponse.model_validate(product).model_dump(mode="json")
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type=event_type,
        event_version=EVENT_VERSION,
        producer="catalog-service",
        correlation_id=correlation_id or _current_correlation_id() or uuid.uuid4(),
        payload=payload,
    )


async def enqueue_event(db: AsyncSession, envelope: EventEnvelope) -> IndexOutbox:
    """Вставляет строку outbox в текущую транзакцию (без commit)."""
    row = IndexOutbox(
        event_id=envelope.event_id, envelope=envelope.model_dump(mode="json")
    )
    db.add(row)
    await db.flush()
    return row
