"""Конфигурация cart-сервиса.

Наследует общий :class:`common.config.BaseAppSettings` и добавляет параметры
корзин: URL Redis (единственное хранилище состояния), Catalog-сервис,
таймаут HTTP-вызова и параметры circuit breaker, TTL корзины и лимиты
(максимум различных товаров, максимум количества).
"""

from common.config import BaseAppSettings


class Settings(BaseAppSettings):
    """Настройки cart-сервиса.

    Дополнительно к базовым полям добавляет:
        redis_url: URL Redis (унаследован; для корзин — источник истины).
        catalog_base_url: Базовый URL Catalog-сервиса.
        catalog_http_timeout: Таймаут HTTP-вызова Catalog, секунды.
        breaker_failure_threshold: Порог отказов circuit breaker.
        breaker_open_seconds: Время открытого состояния breaker, секунды.
        cart_ttl_seconds: TTL ключа корзины, секунды (обновляется при каждой записи).
        max_distinct_items: Максимум различных товаров в одной корзине.
        max_quantity: Максимум количества одного товара в корзине.
        otel_exporter_otlp_endpoint: Endpoint OTLP; пусто — tracing выключен.
    """

    app_name: str = "cart-service"
    catalog_base_url: str = "http://localhost:8000"
    catalog_http_timeout: float = 3.0
    breaker_failure_threshold: int = 5
    breaker_open_seconds: float = 30.0
    cart_ttl_seconds: int = 604800
    max_distinct_items: int = 50
    max_quantity: int = 100
    otel_exporter_otlp_endpoint: str = ""


settings = Settings()
