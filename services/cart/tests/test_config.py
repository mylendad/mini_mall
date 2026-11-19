"""Юнит-тест настроек: чтение из переменных окружения (задача 1.2)."""

from app.config import Settings


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis-host:6379/3")
    monkeypatch.setenv("CATALOG_BASE_URL", "http://catalog:9000")
    monkeypatch.setenv("CATALOG_HTTP_TIMEOUT", "2.5")
    monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("BREAKER_OPEN_SECONDS", "10.0")
    monkeypatch.setenv("CART_TTL_SECONDS", "3600")
    monkeypatch.setenv("MAX_DISTINCT_ITEMS", "10")
    monkeypatch.setenv("MAX_QUANTITY", "20")
    monkeypatch.setenv("APP_NAME", "cart-service-test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    s = Settings(_env_file=None)

    assert s.redis_url == "redis://redis-host:6379/3"
    assert s.catalog_base_url == "http://catalog:9000"
    assert s.catalog_http_timeout == 2.5
    assert s.breaker_failure_threshold == 3
    assert s.breaker_open_seconds == 10.0
    assert s.cart_ttl_seconds == 3600
    assert s.max_distinct_items == 10
    assert s.max_quantity == 20
    assert s.app_name == "cart-service-test"
    assert s.log_level == "DEBUG"


def test_settings_defaults():
    s = Settings(_env_file=None)

    assert s.app_name == "cart-service"
    assert s.max_quantity == 100
    assert s.catalog_http_timeout > 0
    assert s.cart_ttl_seconds > 0
