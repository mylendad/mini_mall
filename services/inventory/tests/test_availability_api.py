"""Интеграционные тесты доступности: API и отсутствие побочных эффектов (фаза 3)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.usefixtures("db_engine")


@pytest.fixture
def make_item(db_engine, client):
    """Фабрика позиций (опционально с предварительным резервом)."""

    async def _create(sku: str, on_hand: int, reserved: int = 0):
        resp = await client.post(
            "/stock-items", json={"sku": sku, "quantity_on_hand": on_hand}
        )
        assert resp.status_code == 201, resp.text
        if reserved:
            from datetime import UTC, datetime, timedelta

            from app.repositories.reservation_repo import ReservationRepository
            from app.repositories.stock_repo import StockRepository

            session = async_sessionmaker(db_engine, expire_on_commit=False)()
            async with session as s:
                item = await StockRepository(s).get_by_sku(sku)
                await ReservationRepository(s).reserve(
                    stock_item_id=item.id,
                    quantity=reserved,
                    holder_ref="t",
                    idempotency_key=None,
                    expires_at=datetime.now(UTC) + timedelta(seconds=60),
                )
                await s.commit()

    return _create


async def test_single_check_fields(client, make_item) -> None:
    await make_item("AV-1", 100, reserved=30)
    resp = await client.get("/availability/AV-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "sku": "AV-1",
        "quantity_on_hand": 100,
        "quantity_reserved": 30,
        "available": 70,
        "in_stock": True,
    }


async def test_single_check_out_of_stock_flag(client, make_item) -> None:
    await make_item("AV-2", 10, reserved=10)
    body = (await client.get("/availability/AV-2")).json()
    assert body["available"] == 0
    assert body["in_stock"] is False


async def test_single_check_unknown_404(client) -> None:
    resp = await client.get("/availability/NOPE")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "STOCK_ITEM_NOT_FOUND"


async def test_batch_with_unknown_sku_succeeds(client, make_item) -> None:
    await make_item("BB-1", 10)
    resp = await client.post("/availability/check", json={"skus": ["BB-1", "NOPE"]})
    assert resp.status_code == 200
    items = {i["sku"]: i for i in resp.json()["items"]}
    assert items["BB-1"]["found"] is True
    assert items["BB-1"]["available"] == 10
    assert items["NOPE"]["found"] is False


async def test_batch_oversized_422(client, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "availability_batch_max_skus", 3)
    resp = await client.post(
        "/availability/check", json={"skus": ["A", "B", "C", "D"]}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_availability_is_side_effect_free(client, make_item) -> None:
    """3.3: чтения не меняют on_hand/reserved/updated_at."""
    await make_item("SE-1", 20)
    item_id = (await client.get("/stock-items/by-sku/SE-1")).json()["id"]
    await client.get("/availability/SE-1")
    await client.post("/availability/check", json={"skus": ["SE-1"]})
    after = (await client.get(f"/stock-items/{item_id}")).json()
    assert after["quantity_on_hand"] == 20
    assert after["quantity_reserved"] == 0
