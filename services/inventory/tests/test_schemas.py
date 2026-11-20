"""Unit-тесты схем Pydantic: границы валидации (количества, SKU, TTL)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.inventory import (
    AvailabilityBatchRequest,
    ReservationCreate,
    StockItemAdjust,
    StockItemCreate,
    StockItemThresholdUpdate,
)
from app.schemas.saga import parse_command


class TestStockItemCreate:
    def test_valid(self) -> None:
        item = StockItemCreate(sku="SKU-1", quantity_on_hand=10)
        assert item.quantity_on_hand == 10
        assert item.low_stock_threshold == 0

    def test_negative_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StockItemCreate(sku="SKU-1", quantity_on_hand=-1)

    def test_zero_quantity_ok(self) -> None:
        assert StockItemCreate(sku="SKU-1", quantity_on_hand=0)

    def test_negative_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StockItemCreate(sku="SKU-1", quantity_on_hand=1, low_stock_threshold=-1)

    def test_empty_sku_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StockItemCreate(sku="  ", quantity_on_hand=1)

    def test_catalog_product_id_optional(self) -> None:
        pid = uuid.uuid4()
        item = StockItemCreate(sku="SKU-1", quantity_on_hand=1, catalog_product_id=pid)
        assert item.catalog_product_id == pid


class TestStockItemAdjust:
    def test_valid(self) -> None:
        adj = StockItemAdjust(delta=-5, reason="damaged")
        assert adj.delta == -5

    def test_empty_reason_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StockItemAdjust(delta=1, reason=" ")


class TestThresholdUpdate:
    def test_valid(self) -> None:
        assert StockItemThresholdUpdate(low_stock_threshold=5).low_stock_threshold == 5

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StockItemThresholdUpdate(low_stock_threshold=-1)


class TestReservationCreate:
    def test_valid(self) -> None:
        r = ReservationCreate(sku="SKU-1", quantity=3, holder_ref="order-1")
        assert r.ttl_seconds is None

    def test_zero_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReservationCreate(sku="SKU-1", quantity=0, holder_ref="o")

    def test_negative_ttl_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReservationCreate(
                sku="SKU-1", quantity=1, holder_ref="o", ttl_seconds=-1
            )

    def test_empty_holder_ref_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReservationCreate(sku="SKU-1", quantity=1, holder_ref="")

    def test_non_positive_quantity_boundaries(self) -> None:
        with pytest.raises(ValidationError):
            ReservationCreate(sku="SKU-1", quantity=-10, holder_ref="o")


class TestAvailabilityBatch:
    def test_valid(self) -> None:
        req = AvailabilityBatchRequest(skus=["A", "B"])
        assert req.skus == ["A", "B"]

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AvailabilityBatchRequest(skus=[])

    def test_blank_sku_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AvailabilityBatchRequest(skus=["A", "  "])


class TestSagaCommand:
    def test_parse_valid(self) -> None:
        cmd = parse_command(
            {
                "command": "reserve",
                "order_id": "order-1",
                "items": [{"sku": "SKU-1", "quantity": 2}],
                "saga_ref": "saga-1",
                "correlation_id": str(uuid.uuid4()),
            }
        )
        assert cmd.command == "reserve"
        assert cmd.items[0].quantity == 2

    def test_unknown_command_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_command({"command": "cancel", "order_id": "o", "items": []})

    def test_empty_items_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_command({"command": "reserve", "order_id": "o", "items": []})

    def test_non_positive_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_command(
                {
                    "command": "reserve",
                    "order_id": "o",
                    "items": [{"sku": "S", "quantity": 0}],
                }
            )

    def test_missing_order_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_command(
                {"command": "confirm", "items": [{"sku": "S", "quantity": 1}]}
            )
