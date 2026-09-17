"""Единый конверт событий для Kafka и других транспортов.

Гарантирует одинаковую структуру сообщений между сервисами и даёт механизм
версионирования схемы события.
"""
from datetime import UTC, datetime
from typing import Any

from pydantic import UUID4, BaseModel, Field


class EventEnvelope(BaseModel):
    """Конверт события, передаваемого между сервисами.

    Атрибуты:
        event_id: Уникальный идентификатор события.
        event_type: Тип события (например, ``user.registered``).
        event_version: Версия схемы события.
        occurred_at: Время возникновения события (UTC).
        producer: Имя сервиса-источника события.
        correlation_id: Сквозной идентификатор корреляции запроса.
        payload: Полезная нагрузка события.
    """
    event_id: UUID4
    event_type: str
    event_version: int = 1
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    producer: str
    correlation_id: UUID4
    payload: dict[str, Any]
