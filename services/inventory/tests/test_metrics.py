"""Интеграционные тесты метрик Prometheus (9.1)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("db_engine")


def _counter_value(metrics_text: str, name: str, labels: str) -> float:
    """Читает значение счётчика по имени и строке labels (labels="" — _total)."""
    import re

    pattern = rf"^{re.escape(name)}{{{re.escape(labels)}}} (\d+\.?\d*)$"
    for line in metrics_text.splitlines():
        m = re.match(pattern, line)
        if m:
            return float(m.group(1))
    return 0.0


async def _metrics(client) -> str:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    return resp.text


async def _snapshot(client) -> dict[str, float]:
    text = await _metrics(client)
    return {
        "reserved": _counter_value(
            text, "inventory_reservations_total", 'outcome="reserved"'
        ),
        "insufficient": _counter_value(
            text, "inventory_reservations_total", 'outcome="insufficient"'
        ),
        "confirmed": _counter_value(
            text, "inventory_reservations_total", 'outcome="confirmed"'
        ),
        "released": _counter_value(
            text, "inventory_reservations_total", 'outcome="released"'
        ),
    }


async def _make_stock(client, sku, on_hand):
    resp = await client.post(
        "/stock-items", json={"sku": sku, "quantity_on_hand": on_hand}
    )
    assert resp.status_code == 201


async def test_reservation_counters_increment(client) -> None:
    await _make_stock(client, "MT-1", 100)
    before = await _snapshot(client)

    r = (
        await client.post(
            "/reservations",
            json={"sku": "MT-1", "quantity": 5, "holder_ref": "o"},
        )
    ).json()
    await client.post(f"/reservations/{r['id']}/confirm")
    r2 = (
        await client.post(
            "/reservations",
            json={"sku": "MT-1", "quantity": 3, "holder_ref": "o2"},
        )
    ).json()
    await client.post(f"/reservations/{r2['id']}/release")
    await client.post(
        "/reservations", json={"sku": "MT-1", "quantity": 500, "holder_ref": "o3"}
    )  # insufficient

    after = await _snapshot(client)
    # Два успешных резерва (5 и 3), один confirm, один release, один отказ.
    assert after["reserved"] == before["reserved"] + 2
    assert after["confirmed"] == before["confirmed"] + 1
    assert after["released"] == before["released"] + 1
    assert after["insufficient"] == before["insufficient"] + 1


async def test_outbox_gauge_exposed(client) -> None:
    await _make_stock(client, "MT-2", 1)
    text = await _metrics(client)
    assert "inventory_outbox_pending" in text


async def test_expiration_counters_exposed(client) -> None:
    text = await _metrics(client)
    assert "inventory_expiration_runs_total" in text
    assert "inventory_expiration_processed_total" in text
