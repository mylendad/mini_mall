"""Интеграционные тесты Catalog-клиента (задача 3.2) на HTTP-стабе.

Проверяется: таймаут прерывает зависший вызов в пределах настроенного
лимита; breaker размыкается после порога и fail-fast; half-open
восстановление. Маппинг статусов — на MockTransport.
"""

from __future__ import annotations

import time
import uuid

import httpx
import pytest

from app.application.protocols import CatalogUnavailable
from app.config import settings
from app.infrastructure.breaker import CircuitBreaker
from app.infrastructure.catalog_client import CatalogClient
from tests.stubs import StubCatalogServer, StubResponse

PID = uuid.uuid4()


def make_client(
    handler=None, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    if transport is not None:
        return httpx.AsyncClient(transport=transport, base_url="http://stub")
    assert handler is not None
    return httpx.AsyncClient(base_url="http://stub")  # overridden per-test


async def test_missing_product_maps_to_missing():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, json={"detail": "not found"})
    )
    async with make_client(transport=transport) as client:
        gateway = CatalogClient(client, breaker=CircuitBreaker(5, 30.0))
        assert await gateway.validate_product(PID) == "missing"


async def test_inactive_product_maps_to_inactive():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"id": str(PID), "is_active": False})
    )
    async with make_client(transport=transport) as client:
        gateway = CatalogClient(client, breaker=CircuitBreaker(5, 30.0))
        assert await gateway.validate_product(PID) == "inactive"


async def test_active_product_maps_to_active():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"id": str(PID), "is_active": True})
    )
    async with make_client(transport=transport) as client:
        gateway = CatalogClient(client, breaker=CircuitBreaker(5, 30.0))
        assert await gateway.validate_product(PID) == "active"


async def test_timeout_aborts_within_configured_limit():
    """Стаб молчит дольше таймаута -> ``CatalogUnavailable`` быстрее лимита."""
    original = settings.catalog_http_timeout
    server = StubCatalogServer(
        lambda path: StubResponse(status=200, body=b'{"is_active": true}', delay=5.0)
    )
    await server.start()
    try:
        settings.catalog_http_timeout = 0.5
        async with httpx.AsyncClient(base_url=server.base_url) as client:
            gateway = CatalogClient(client, breaker=CircuitBreaker(5, 30.0))
            start = time.monotonic()
            with pytest.raises(CatalogUnavailable):
                await gateway.validate_product(PID)
            elapsed = time.monotonic() - start
        assert elapsed < 3.0  # зависший вызов прерван, а не выполнен полностью
    finally:
        settings.catalog_http_timeout = original
        await server.stop()


async def test_breaker_opens_after_threshold_and_fails_fast():
    """Порог подряд сбоев (зависшие ответы) -> открытый breaker -> fail-fast."""
    original = settings.catalog_http_timeout
    server = StubCatalogServer(
        lambda path: StubResponse(status=200, body=b'{"is_active": true}', delay=5.0)
    )
    await server.start()
    try:
        settings.catalog_http_timeout = 0.3
        breaker = CircuitBreaker(failure_threshold=3, open_seconds=30.0)
        async with httpx.AsyncClient(base_url=server.base_url) as client:
            gateway = CatalogClient(client, breaker=breaker)
            for _ in range(3):
                with pytest.raises(CatalogUnavailable):
                    await gateway.validate_product(PID)
            assert breaker.state == "open"

            calls_before = len(server.requests)
            with pytest.raises(CatalogUnavailable):
                await gateway.validate_product(PID)
            assert len(server.requests) == calls_before  # fail-fast: сокет не трогали
    finally:
        settings.catalog_http_timeout = original
        await server.stop()


async def test_half_open_recovery_succeeds():
    """После open_seconds одна пробная попытка: успех -> closed."""
    original = settings.catalog_http_timeout
    settings.catalog_http_timeout = 0.5
    behavior = {"delay": 5.0}

    async def handler(path: str) -> StubResponse:
        return StubResponse(status=200, body=b'{"is_active": true}', delay=behavior["delay"])

    server = StubCatalogServer(handler)
    await server.start()
    try:
        breaker = CircuitBreaker(failure_threshold=2, open_seconds=0.0)
        async with httpx.AsyncClient(base_url=server.base_url) as client:
            gateway = CatalogClient(client, breaker=breaker)
            for _ in range(2):
                with pytest.raises(CatalogUnavailable):
                    await gateway.validate_product(PID)
            assert breaker.state == "open"

            behavior["delay"] = 0.0  # «Catalog восстановился»
            assert await gateway.validate_product(PID) == "active"
            assert breaker.state == "closed"
    finally:
        settings.catalog_http_timeout = original
        await server.stop()


async def test_server_error_maps_to_unavailable():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, json={"detail": "boom"})
    )
    async with make_client(transport=transport) as client:
        gateway = CatalogClient(client, breaker=CircuitBreaker(5, 30.0))
        with pytest.raises(CatalogUnavailable):
            await gateway.validate_product(PID)
