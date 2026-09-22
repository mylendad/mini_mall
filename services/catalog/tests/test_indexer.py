"""Юнит-тесты построения ES-документа по строке продукта (8.1)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.models.catalog import Product
from app.services.indexer import product_document


def _product(**overrides) -> Product:
    defaults = {
        "id": uuid4(),
        "category_id": uuid4(),
        "name": "Wireless Mouse",
        "description": None,
        "price": Decimal("19.99"),
        "currency": "USD",
        "sku": "MOUSE-001",
        "attributes": {"color": "black"},
        "is_active": True,
        "created_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    }
    defaults.update(overrides)
    product = Product(**defaults)
    product.id = defaults["id"]
    return product


def test_document_shape_matches_mapping():
    product = _product()
    doc = product_document(product, category_name="Electronics")
    assert doc["id"] == str(product.id)
    assert doc["sku"] == "MOUSE-001"
    assert doc["name"] == "Wireless Mouse"
    assert doc["category_id"] == str(product.category_id)
    assert doc["category_name"] == "Electronics"
    assert doc["price"] == 19.99
    assert doc["currency"] == "USD"
    assert doc["attributes"] == {"color": "black"}
    assert doc["is_active"] is True
    assert doc["created_at"] == int(product.created_at.timestamp() * 1000)


def test_document_preserves_description_none_and_inactive():
    product = _product(description=None, is_active=False)
    doc = product_document(product, category_name="X")
    assert doc["description"] is None
    assert doc["is_active"] is False


def test_document_defaults_attributes_to_empty_dict():
    doc = product_document(_product(attributes={}), category_name="X")
    assert doc["attributes"] == {}
