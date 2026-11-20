"""Smoke-тест: приложение поднимается и отвечает на /health/live."""

from __future__ import annotations


async def test_app_serves_health_live(client) -> None:
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}
