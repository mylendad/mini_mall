"""Unit-тесты ошибок: пары «код ↔ статус ↔ сообщение» и маппер IntegrityError."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from common.errors import ErrorCode
from sqlalchemy.exc import IntegrityError

from app.errors import IntegrityErrorMapper


def test_error_code_pairs() -> None:
    assert ErrorCode.STOCK_ITEM_NOT_FOUND.status_code == HTTPStatus.NOT_FOUND
    assert ErrorCode.STOCK_ITEM_NOT_FOUND.message == "Stock item not found"
    assert ErrorCode.INSUFFICIENT_STOCK.status_code == HTTPStatus.CONFLICT
    assert ErrorCode.INSUFFICIENT_STOCK.message == "Insufficient stock"
    assert ErrorCode.RESERVATION_NOT_FOUND.status_code == HTTPStatus.NOT_FOUND
    assert ErrorCode.RESERVATION_NOT_FOUND.message == "Reservation not found"
    assert ErrorCode.INVALID_RESERVATION_STATE.status_code == HTTPStatus.CONFLICT
    assert (
        ErrorCode.INVALID_RESERVATION_STATE.message
        == "Reservation is not in active state"
    )
    assert ErrorCode.DUPLICATE_SKU.status_code == HTTPStatus.CONFLICT
    assert str(ErrorCode.INSUFFICIENT_STOCK) == "INSUFFICIENT_STOCK"


def _exc_with_constraint(constraint: str) -> IntegrityError:
    cause = type("DbApiError", (Exception,), {"constraint_name": constraint})()
    return IntegrityError(statement=None, params=None, orig=cause)


def test_mapper_stock_item_sku_duplicate() -> None:
    detail = IntegrityErrorMapper().stock_item_write(
        _exc_with_constraint("stock_items_sku_key")
    )
    assert detail is not None
    assert detail["code"] == "DUPLICATE_SKU"
    assert detail["message"] == "Stock item SKU already exists"
    assert detail["details"] is None


def test_mapper_reservation_idempotency_duplicate() -> None:
    detail = IntegrityErrorMapper().reservation_write(
        _exc_with_constraint("reservations_idempotency_key_key")
    )
    assert detail is not None
    assert detail["code"] == "DUPLICATE_SKU"
    assert "idempotency" in detail["message"]


def test_mapper_unknown_constraint() -> None:
    assert IntegrityErrorMapper().stock_item_write(
        _exc_with_constraint("other_key")
    ) is None


@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.STOCK_ITEM_NOT_FOUND,
        ErrorCode.INSUFFICIENT_STOCK,
        ErrorCode.RESERVATION_NOT_FOUND,
        ErrorCode.INVALID_RESERVATION_STATE,
    ],
)
def test_error_detail_shape(code: ErrorCode) -> None:
    from common.errors import error_detail

    detail = error_detail(code)
    assert detail["code"] == str(code)
    assert detail["message"] == code.message
