"""Модель outbox-очереди индексации продуктов.

Каждая строка содержит конверт события :class:`common.events.EventEnvelope`
(``product.created``/``product.updated``/``product.deleted``) и записывается в
той же транзакции, что и изменение продукта. Фоновый релей перечитывает
авторитетное состояние продукта из PostgreSQL и применяет операцию в
Elasticsearch, после чего помечает строку обработанной. При откате
продуктовой транзакции строка outbox не выживает — атомарность гарантирована
тем, что запись в outbox находится в той же транзакции.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IndexOutbox(Base):
    """Очередь синхронизации PostgreSQL -> Elasticsearch.

    Атрибуты:
        id: Числовой первичный ключ.
        event_id: UUID события (уникален — идемпотентность обработки).
        envelope: Конверт события :class:`common.events.EventEnvelope` (JSONB).
        status: ``pending``/``processed``.
        attempt_count: Число попыток обработки.
        last_error: Текст последней ошибки.
        created_at: Время постановки в очередь (UTC).
        processed_at: Время успешной обработки (UTC).
    """

    __tablename__ = "index_outbox"
    __table_args__ = (
        Index("ix_index_outbox_status_created_at", "status", "created_at"),
        Index("ix_index_outbox_processed_at", "processed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True, nullable=False
    )
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
