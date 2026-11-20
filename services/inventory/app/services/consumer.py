"""Kafka-потребитель команд саги (aiokafka).

Подписывается на командный топик (consumer group из настроек), разбирает
конверт события с командой и передаёт в seam :mod:`app.services.saga`.
Offset коммитится вручную только после успешной обработки (commit/ack);
при ошибке обработки offset не двигается — команда будет доставлена
снова (идемпотентность гарантирует отсутствие двойного эффекта).
"""

from __future__ import annotations

import asyncio
import json
import uuid

import structlog
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_maker
from app.schemas.saga import parse_command
from app.services.saga import SagaCommandHandler

logger = structlog.get_logger()


def create_consumer(
    bootstrap_servers: str | None = None,
    group_id: str | None = None,
    topics: list[str] | None = None,
) -> AIOKafkaConsumer:
    """Создаёт настроенный :class:`AIOKafkaConsumer` (не запускает его)."""
    return AIOKafkaConsumer(
        *(topics or [settings.commands_topic]),
        bootstrap_servers=bootstrap_servers or settings.kafka_bootstrap_servers,
        group_id=group_id or settings.consumer_group,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )


async def handle_message(db: AsyncSession, message) -> bool:
    """Обрабатывает одно сообщение команды; ``True`` — акать offset.

    Некорректная (не разбираемая) команда логируется и акается без
    обработки — «ядовитые» команды не блокируют партицию.
    """
    payload = message.value
    if not isinstance(payload, dict):
        logger.warning("consumer.malformed_payload", type=type(payload).__name__)
        return True
    try:
        command = parse_command(payload)
    except ValidationError as exc:
        logger.warning("consumer.invalid_command", error=str(exc))
        return True
    event_id = getattr(message, "event_id", None) or _envelope_event_id(payload)
    if event_id is None:
        logger.warning("consumer.missing_event_id")
        return True
    handler = SagaCommandHandler(db)
    return await handler.handle(uuid.UUID(str(event_id)), command)


def _envelope_event_id(payload: dict) -> uuid.UUID | None:
    """Извлекает ``event_id`` из конверта события в payload."""
    raw = payload.get("event_id")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            return None
    return None


async def consume_commands(stop_event: asyncio.Event) -> None:
    """Бесконечный цикл потребителя; останавливается установкой ``stop_event``."""
    logger.info("consumer.started", topic=settings.commands_topic)
    consumer = create_consumer()
    await consumer.start()
    try:
        async for message in consumer:
            if stop_event.is_set():
                break
            try:
                async with async_session_maker() as db:
                    ok = await handle_message(db, message)
                if ok:
                    await consumer.commit()
            except asyncio.CancelledError:
                raise
            except KafkaError as exc:
                logger.error("consumer.kafka_error", error=str(exc))
            except Exception as exc:  # noqa: BLE001 - не роняем цикл потребителя
                logger.error("consumer.process_failed", error=str(exc))
    finally:
        try:
            await consumer.stop()
        except Exception as exc:  # noqa: BLE001 - остановка не должна падать
            logger.warning("consumer.stop_failed", error=str(exc))
        logger.info("consumer.stopped")
