"""Redis read-through кэш точечных чтений продуктов (D11).

Ключ ``catalog:product:{id}`` с TTL из настроек ограничивает устаревание;
при мутации (update/delete) ключ активно инвалидируется после commit в PG.

Резилиентность: все операции завернуты — при недоступности Redis (``RedisError``/
``OSError``) ошибка логируется, а чтение идёт напрямую из PostgreSQL, не ломая
пользовательский запрос (требование спеки «cache failures MUST NOT break the
read path»). Модуль не поднимает соединение на import: клиент создаётся в
``lifespan`` через :func:`init`, поэтому в тестах без lifespan кэш-слой
безопасно выключен и промахи уходят в БД.
"""

from __future__ import annotations

import redis.asyncio as aioredis
import structlog

from app.config import settings

logger = structlog.get_logger()

PRODUCT_KEY_PREFIX = "catalog:product"

_client: aioredis.Redis | None = None
_enabled = False


def init() -> None:
    """Создаёт Redis-клиент с явными таймаутами (вызывается в lifespan)."""
    global _client, _enabled
    _client = aioredis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    _enabled = True


async def close() -> None:
    """Закрывает Redis-клиент; последующие обращения становятся no-op."""
    global _client, _enabled
    if _client is not None:
        await _client.aclose()
    _client = None
    _enabled = False


def _product_key(product_id) -> str:
    return f"{PRODUCT_KEY_PREFIX}:{product_id}"


async def get_product(product_id) -> str | None:
    """Возвращает сырое JSON-значение из кэша или ``None`` (промах/сбой)."""
    if not _enabled or _client is None:
        return None
    try:
        return await _client.get(_product_key(product_id))
    except Exception as exc:  # noqa: BLE001 - кэш не должен ломать чтение
        logger.warning("cache.read_failed", error=str(exc))
        return None


async def set_product(product_id, value: str) -> None:
    """Кладёт значение с TTL ``cache_ttl_seconds``; сбой логируется, не бросает."""
    if not _enabled or _client is None:
        return
    try:
        await _client.set(
            _product_key(product_id), value, ex=settings.cache_ttl_seconds
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache.write_failed", error=str(exc))


async def delete_product(product_id) -> None:
    """Инвалидирует ключ (после commit PG); сбой логируется, не бросает."""
    if not _enabled or _client is None:
        return
    try:
        await _client.delete(_product_key(product_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache.invalidate_failed", error=str(exc))
