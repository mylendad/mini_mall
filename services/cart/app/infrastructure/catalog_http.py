"""Жизненный цикл httpx-клиента Catalog (graceful shutdown, задача 1.4).

Клиент создаётся в ``lifespan`` и закрывается при выключении; сам не
поднимает соединений на import.
"""

from __future__ import annotations

import httpx

from app.config import settings

_client: httpx.AsyncClient | None = None


def init() -> None:
    """Инициализирует клиент Catalog (вызывается в lifespan)."""
    global _client
    _client = httpx.AsyncClient(base_url=settings.catalog_base_url)


async def close() -> None:
    """Закрывает клиент Catalog (graceful shutdown)."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def get_catalog_http_client() -> httpx.AsyncClient:
    """Возвращает инициализированный клиент (используется роутером add)."""
    if _client is None:
        init()
    assert _client is not None
    return _client
