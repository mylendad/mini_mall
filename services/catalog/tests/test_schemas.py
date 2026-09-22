"""Юнит-тесты валидации схем каталога (8.1)."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.catalog import (
    CategoryCreate,
    CategoryUpdate,
    ProductCreate,
    ProductUpdate,
)


def test_category_name_stripped():
    category = CategoryCreate(name="  Electronics  ", description="d")
    assert category.name == "Electronics"


def test_category_blank_name_rejected():
    with pytest.raises(ValidationError):
        CategoryCreate(name="   ")


def test_category_update_none_name_ok():
    update = CategoryUpdate(name=None)
    assert update.name is None


def test_category_update_blank_name_rejected():
    with pytest.raises(ValidationError):
        CategoryUpdate(name="  ")


def _valid_product() -> dict:
    return {
        "category_id": str(uuid4()),
        "name": "Wireless Mouse",
        "description": "Ergonomic",
        "price": "19.99",
        "currency": "USD",
        "sku": "MOUSE-001",
        "attributes": {"color": "black"},
        "is_active": True,
    }


def test_product_valid_price_parsed_as_decimal():
    product = ProductCreate.model_validate(_valid_product())
    assert product.price == Decimal("19.99")
    assert product.attributes == {"color": "black"}


@pytest.mark.parametrize("price", ["0", "-1", "1.999", "0.001"])
def test_product_invalid_price_rejected(price):
    payload = _valid_product()
    payload["price"] = price
    with pytest.raises(ValidationError):
        ProductCreate.model_validate(payload)


@pytest.mark.parametrize("currency", ["usd", "US", "USDD", "us1"])
def test_product_invalid_currency_rejected(currency):
    payload = _valid_product()
    payload["currency"] = currency
    with pytest.raises(ValidationError):
        ProductCreate.model_validate(payload)


@pytest.mark.parametrize("sku", ["bad sku", "", "a" * 65, "!x"])
def test_product_invalid_sku_rejected(sku):
    payload = _valid_product()
    payload["sku"] = sku
    with pytest.raises(ValidationError):
        ProductCreate.model_validate(payload)


def test_product_name_blank_rejected():
    payload = _valid_product()
    payload["name"] = " "
    with pytest.raises(ValidationError):
        ProductCreate.model_validate(payload)


def test_product_attributes_default_empty():
    payload = _valid_product()
    payload.pop("attributes")
    product = ProductCreate.model_validate(payload)
    assert product.attributes == {}


def test_product_update_partial():
    update = ProductUpdate.model_validate({"price": "9.50"})
    assert update.price == Decimal("9.50")
    assert update.name is None
