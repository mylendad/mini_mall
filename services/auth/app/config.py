"""Конфигурация сервиса аутентификации.

Наследует общий :class:`common.config.BaseAppSettings` и добавляет
сервисные параметры: секрет JWT и время жизни токенов. Значения можно
переопределять переменными окружения или файлом ``.env``.
"""
from common.config import BaseAppSettings


class Settings(BaseAppSettings):
    """Настройки auth-сервиса.

    Дополнительно к базовым полям добавляет:
        jwt_secret: Секрет для подписи JWT access-токенов (HS256).
            Должен быть не короче 32 байт. В production задаётся
            переменной окружения.
        access_token_expire_minutes: Время жизни access-токена
            (по умолчанию 15 минут).
        refresh_token_expire_days: Время жизни refresh-токена
            (по умолчанию 7 суток).
    """
    app_name: str = "auth-service"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/mini_mall_auth"
    jwt_secret: str = "super-secret-jwt-key-change-in-production-1234567890"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7


settings = Settings()
