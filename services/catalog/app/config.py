"""Конфигурация сервиса каталога.

Наследует общий :class:`common.config.BaseAppSettings` и добавляет параметры
каталога: URL PostgreSQL и Elasticsearch, префикс индекса ES, таймауты
клиента и настройки фонового релея outbox-событий.
"""

from common.config import BaseAppSettings


class Settings(BaseAppSettings):
    """Настройки catalog-сервиса.

    Дополнительно к базовым полям добавляет:
        database_url: URL PostgreSQL (переопределяет базовый — БД каталога
            изолирована, ``mini_mall_catalog``).
        elasticsearch_url: URL Elasticsearch (search-проекция).
        es_index_prefix: Префикс имени индекса продуктов.
        es_request_timeout: Таймаут ES-запроса, секунды.
        es_connect_timeout: Таймаут ES-соединения, секунды.
        outbox_batch_size: Размер пачки строк outbox за один проход релея.
        outbox_poll_interval: Пауза релея между проходами, секунды.
        outbox_max_attempts: Максимум попыток обработки строки outbox.
        outbox_backoff_base: База экспоненциальной задержки между попытками.
        outbox_retention_seconds: Срок жизни обработанных строк outbox (0 — без чистки).
        breaker_failure_threshold: Порог отказов для размыкания circuit breaker.
        breaker_open_seconds: Время открытого состояния breaker, секунды.
        redis_url: URL Redis (read-through кэш точечных чтений продукта).
        cache_ttl_seconds: TTL кэш-ключа продукта, секунды.
        otel_exporter_otlp_endpoint: Endpoint OTLP для трейсов; пусто — tracing выключен.
    """

    app_name: str = "catalog-service"
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/mini_mall_catalog"
    )
    elasticsearch_url: str = "http://localhost:9200"
    es_index_prefix: str = "catalog_products"
    es_request_timeout: float = 5.0
    es_connect_timeout: float = 5.0
    outbox_batch_size: int = 100
    outbox_poll_interval: float = 1.0
    outbox_max_attempts: int = 10
    outbox_backoff_base: float = 1.0
    outbox_retention_seconds: int = 86400
    breaker_failure_threshold: int = 5
    breaker_open_seconds: float = 30.0
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 300
    otel_exporter_otlp_endpoint: str = ""


settings = Settings()
