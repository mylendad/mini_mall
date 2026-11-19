"""Жизненный цикл Redis-клиента cart-сервиса.

Клиент создаётся в ``lifespan`` (app.main) и закрывается при выключении
(SIGTERM — graceful shutdown, задача 1.4). Модуль не поднимает соединение
на import, поэтому тесты без lifespan безопасны.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.config import settings

_client: aioredis.Redis | None = None


def create_client(url: str | None = None) -> aioredis.Redis:
    """Создаёт Redis-клиент с явными таймаутами подключения."""
    return aioredis.Redis.from_url(
        url or settings.redis_url,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )


def init() -> None:
    """Инициализирует глобальный клиент (вызывается в lifespan)."""
    global _client
    _client = create_client()


async def close() -> None:
    """Закрывает глобальный клиент и пул соединений (graceful shutdown)."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def get_client() -> aioredis.Redis:
    """Возвращает инициализированный клиент (используется зависимостями API)."""
    if _client is None:
        init()
    assert _client is not None
    return _client
