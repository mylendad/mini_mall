"""Unit-тесты конфигурации: значения по умолчанию и переопределение из env."""

from __future__ import annotations

from app.config import Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_name == "inventory-service"
    assert "mini_mall_inventory" in settings.database_url
    assert settings.kafka_bootstrap_servers == "localhost:9092"
    assert settings.commands_topic == "inventory.commands"
    assert settings.events_topic == "inventory.events"
    assert settings.consumer_group == "inventory-service"
    assert settings.reservation_default_ttl_seconds == 900
    assert settings.expiration_interval == 30.0
    assert settings.availability_batch_max_skus == 100
    assert settings.outbox_poll_interval == 1.0
    assert settings.outbox_max_attempts == 10
    assert settings.outbox_backoff_base == 1.0
    assert settings.outbox_retention_seconds == 86400
    assert settings.breaker_failure_threshold == 5
    assert settings.breaker_open_seconds == 30.0


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "inv-test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://u:p@h:1/mini_mall_inventory_test",
    )
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker1:9092,broker2:9092")
    monkeypatch.setenv("COMMANDS_TOPIC", "inv.commands.test")
    monkeypatch.setenv("EVENTS_TOPIC", "inv.events.test")
    monkeypatch.setenv("CONSUMER_GROUP", "inv-test")
    monkeypatch.setenv("RESERVATION_DEFAULT_TTL_SECONDS", "60")
    monkeypatch.setenv("EXPIRATION_INTERVAL", "5.0")
    monkeypatch.setenv("OUTBOX_MAX_ATTEMPTS", "3")

    settings = Settings(_env_file=None)
    assert settings.app_name == "inv-test"
    assert settings.database_url.endswith("mini_mall_inventory_test")
    assert settings.kafka_bootstrap_servers == "broker1:9092,broker2:9092"
    assert settings.commands_topic == "inv.commands.test"
    assert settings.events_topic == "inv.events.test"
    assert settings.consumer_group == "inv-test"
    assert settings.reservation_default_ttl_seconds == 60
    assert settings.expiration_interval == 5.0
    assert settings.outbox_max_attempts == 3
