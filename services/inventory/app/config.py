"""Конфигурация сервиса инвентаря.

Наследует общий :class:`common.config.BaseAppSettings` и добавляет параметры
инвентаря: URL PostgreSQL (изолированная БД ``mini_mall_inventory``), адреса
Kafka, имена командного и событийного топиков, consumer group, TTL резервов
по умолчанию, интервал фонового задания истечения и настройки релея outbox.
"""

from common.config import BaseAppSettings


class Settings(BaseAppSettings):
    """Настройки inventory-сервиса.

    Дополнительно к базовым полям добавляет:
        database_url: URL PostgreSQL (переопределяет базовый — БД инвентаря
            изолирована, ``mini_mall_inventory``).
        kafka_bootstrap_servers: Адреса брокеров Kafka (переопределяет базовый).
        commands_topic: Командный топик саги (reserve/confirm/release).
        events_topic: Событийный топик исходов команд и событий склада.
        consumer_group: Consumer group Kafka-потребителя команд.
        reservation_default_ttl_seconds: TTL резерва по умолчанию, секунды.
        expiration_batch_size: Максимальное число резервов за один проход
            задания истечения.
        expiration_interval: Пауза между проходами задания истечения, секунды.
        availability_batch_max_skus: Максимум SKU в пакетной проверке
            доступности (сверх — 422).
        outbox_batch_size: Размер пачки строк outbox за один проход релея.
        outbox_poll_interval: Пауза релея между проходами, секунды.
        outbox_max_attempts: Максимум попыток обработки строки outbox.
        outbox_backoff_base: База экспоненциальной задержки между попытками.
        outbox_retention_seconds: Срок жизни обработанных строк outbox
            (0 — без чистки).
        breaker_failure_threshold: Порог отказов для размыкания circuit breaker.
        breaker_open_seconds: Время открытого состояния breaker, секунды.
        kafka_publish_timeout: Таймаут публикации сообщения в Kafka, секунды.
        otel_exporter_otlp_endpoint: Endpoint OTLP для трейсов; пусто —
            tracing выключен.
    """

    app_name: str = "inventory-service"
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/mini_mall_inventory"
    )
    kafka_bootstrap_servers: str = "localhost:9092"
    commands_topic: str = "inventory.commands"
    events_topic: str = "inventory.events"
    consumer_group: str = "inventory-service"
    reservation_default_ttl_seconds: int = 900
    expiration_batch_size: int = 100
    expiration_interval: float = 30.0
    availability_batch_max_skus: int = 100
    outbox_batch_size: int = 100
    outbox_poll_interval: float = 1.0
    outbox_max_attempts: int = 10
    outbox_backoff_base: float = 1.0
    outbox_retention_seconds: int = 86400
    breaker_failure_threshold: int = 5
    breaker_open_seconds: float = 30.0
    kafka_publish_timeout: float = 5.0
    otel_exporter_otlp_endpoint: str = ""


settings = Settings()
