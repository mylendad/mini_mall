"""Kafka-продюсер для публикации конвертов событий (aiokafka).

Отдельный модуль: продюсер создаётся один раз на процесс (lifespan релея),
публикация — сериализованный JSON конверта :class:`common.events.EventEnvelope`
в событийный топик с ключом = ``event_id`` (порядок внутри партиции по
событию). Таймаут публикации — из настроек сервиса.
"""

from __future__ import annotations

import json

from aiokafka import AIOKafkaProducer
from common.events import EventEnvelope

from app.config import settings


def create_producer(bootstrap_servers: str | None = None) -> AIOKafkaProducer:
    """Создаёт настроенный :class:`AIOKafkaProducer` (не запускает его)."""
    return AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers or settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        acks="all",
        request_timeout_ms=int(settings.kafka_publish_timeout * 1000) + 1000,
    )


async def publish_envelope(
    producer: AIOKafkaProducer, envelope: EventEnvelope
) -> None:
    """Публикует конверт события в событийный топик (ключ = ``event_id``)."""
    await producer.send_and_wait(
        settings.events_topic,
        value=envelope.model_dump(mode="json"),
        key=str(envelope.event_id),
    )
