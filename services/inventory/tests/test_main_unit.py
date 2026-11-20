"""Unit-тесты health/metrics эндпоинтов (движок заглушен)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.main import create_app


class _StubConnectable:
    async def exec_driver_sql(self, sql: str) -> None:
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


class _StubEngine:
    def connect(self):
        return _StubConnectable()


class _FailingEngine:
    def connect(self):
        raise RuntimeError("db down")


@pytest.fixture
def app_with_stub(monkeypatch):
    app = create_app()
    app.router.lifespan_context = _nolifespan(app)
    return app


def _nolifespan(app):
    @asynccontextmanager
    async def lifespan(_app):
        yield

    return lifespan


@pytest.fixture
def health_app(app_with_stub, monkeypatch):
    monkeypatch.setattr(main_module, "engine", _StubEngine())
    return app_with_stub


@pytest.fixture
def sick_app(app_with_stub, monkeypatch):
    monkeypatch.setattr(main_module, "engine", _FailingEngine())
    return app_with_stub


async def test_health_live(health_app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=health_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


async def test_health_ready_ok(health_app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=health_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


async def test_health_ready_db_down(sick_app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=sick_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unhealthy"


async def test_metrics_endpoint(health_app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=health_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 200
    assert b"http_requests_total" in resp.content


async def test_error_envelope_format(health_app) -> None:
    """404 Starlette-роутинга отвечает стандартным конвертом ошибки."""
    async with AsyncClient(
        transport=ASGITransport(app=health_app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/no-such-route", headers={"X-Request-ID": "req-1"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["request_id"] == "req-1"
    assert body["error"]["code"] == "HTTP_ERROR"
