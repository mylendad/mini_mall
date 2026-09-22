"""Конфигурация сервиса аутентификации.

Наследует общий :class:`common.config.BaseAppSettings` и добавляет
сервисные параметры: секрет JWT и время жизни токенов. Значения можно
переопределять переменными окружения или файлом ``.env``.
"""

from common.config import BaseAppSettings
from pydantic import model_validator

DEFAULT_JWT_SECRET = "super-secret-jwt-key-change-in-production-1234567890"


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
        gateway_secret: Общий секрет API Gateway, через который сервис
            доверяет заголовкам ``X-User-ID``/``X-User-Roles``. В
            production обязателен: без него доступ через доверенные
            заголовки запрещён (fail-closed).
    """

    app_name: str = "auth-service"
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/mini_mall_auth"
    )
    jwt_secret: str = DEFAULT_JWT_SECRET
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    gateway_secret: str = ""

    @model_validator(mode="after")
    def _production_requires_real_secrets(self) -> "Settings":
        """В production запрещает стартовать с дефолтными секретами.

        Сервис аутентификации не должен работать с известным из исходников
        JWT-секретом или без секрета API Gateway: оба случая открывают
        подделку токенов и обход доверенного контура.
        """
        if self.environment == "production":
            if self.jwt_secret == DEFAULT_JWT_SECRET:
                raise ValueError(
                    "JWT_SECRET must be set to a non-default value in production"
                )
            if not self.gateway_secret:
                raise ValueError("GATEWAY_SECRET must be set in production")
        return self


settings = Settings()
