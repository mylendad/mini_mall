"""Базовые настройки микросервисов.

Содержит класс :class:`BaseAppSettings` — единую точку входа для конфигурации
конкретного сервиса. Каждый сервис наследует его и переопределяет только те
поля, которые ему нужны (например, ``services/auth/app/config.py``).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAppSettings(BaseSettings):
    """Базовый класс настроек сервиса.

    Параметры читаются из переменных окружения и файла ``.env`` (переменные
    окружения имеют приоритет). Неизвестные переменные окружения игнорируются.

    Атрибуты (со значениями по умолчанию):
        app_name: Название сервиса.
        environment: Окружение (development/staging/production).
        log_level: Уровень логирования.
        database_url: URL подключения к PostgreSQL.
        redis_url: URL подключения к Redis.
        kafka_bootstrap_servers: Адреса брокеров Kafka.

    Сервисы не должны переопределять ``model_config`` без необходимости —
    поведение по умолчанию (чтение ``.env``, ``extra="ignore"``) задаётся здесь.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    app_name: str = "e-commerce-service"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    redis_url: str = "redis://localhost:6379/0"
    kafka_bootstrap_servers: str = "localhost:9092"
