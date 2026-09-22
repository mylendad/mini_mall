"""Юнит-тесты обработки гонок на уникальных ограничениях (ADR-0001, п. 1).

``repo.create()``/``repo.update()`` делают ``flush()`` внутри; при конкурентной
записи нарушение ограничений (unique SKU, FK на категорию) всплывает на
``flush``, до ``commit()``. Маппер обязан переводить его в 409/422, а не
в скрытый 500.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy.exc as saexc
from fastapi import HTTPException

from app.models.catalog import Category, Product
from app.schemas.catalog import (
    CategoryCreate,
    CategoryUpdate,
    ProductCreate,
    ProductUpdate,
)
from app.services.categories import CategoriesService
from app.services.products import ProductsService


def _fake_integrity(constraint_name: str | None) -> saexc.IntegrityError:
    orig = SimpleNamespace(diag=SimpleNamespace(constraint_name=constraint_name))
    return saexc.IntegrityError("stmt", {"params": {}}, orig)


def _product(**overrides) -> Product:
    defaults = {
        "id": uuid4(),
        "category_id": uuid4(),
        "name": "Widget",
        "description": None,
        "price": Decimal("10.00"),
        "currency": "USD",
        "sku": "SKU-1",
        "attributes": {},
        "is_active": True,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    product = Product(**defaults)
    product.id = defaults["id"]
    return product


def _category(**overrides) -> Category:
    defaults = {
        "id": uuid4(),
        "name": "Category",
        "description": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    category = Category(**defaults)
    category.id = defaults["id"]
    return category


class TestProductCreateRace:
    async def test_duplicate_sku_on_flush_is_409(self):
        db = AsyncMock()
        svc = ProductsService(db)
        svc._category_exists = AsyncMock(return_value=True)
        svc.repo.get_by_sku = AsyncMock(return_value=None)
        svc.repo.create = AsyncMock(side_effect=_fake_integrity("products_sku_key"))

        payload = ProductCreate(
            category_id=uuid4(),
            name="Widget",
            price=Decimal("1.00"),
            currency="USD",
            sku="SKU-X",
        )
        with pytest.raises(HTTPException) as exc_info:
            await svc.create(payload)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "DUPLICATE_SKU"
        db.rollback.assert_awaited_once()

    async def test_fk_violation_on_flush_is_422(self):
        db = AsyncMock()
        svc = ProductsService(db)
        svc._category_exists = AsyncMock(return_value=True)
        svc.repo.get_by_sku = AsyncMock(return_value=None)
        svc.repo.create = AsyncMock(
            side_effect=_fake_integrity("products_category_id_fkey")
        )

        payload = ProductCreate(
            category_id=uuid4(),
            name="Widget",
            price=Decimal("1.00"),
            currency="USD",
            sku="SKU-Y",
        )
        with pytest.raises(HTTPException) as exc_info:
            await svc.create(payload)
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_CATEGORY"
        db.rollback.assert_awaited_once()

    async def test_unrecognized_constraint_is_rewrapped(self):
        db = AsyncMock()
        svc = ProductsService(db)
        svc._category_exists = AsyncMock(return_value=True)
        svc.repo.get_by_sku = AsyncMock(return_value=None)
        svc.repo.create = AsyncMock(side_effect=_fake_integrity("something_else"))

        payload = ProductCreate(
            category_id=uuid4(),
            name="Widget",
            price=Decimal("1.00"),
            currency="USD",
            sku="SKU-Z",
        )
        with pytest.raises(saexc.IntegrityError):
            await svc.create(payload)
        db.rollback.assert_awaited_once()


class TestProductUpdateRace:
    async def test_duplicate_sku_on_flush_is_409(self):
        existing = _product(sku="SKU-B")
        db = AsyncMock()
        svc = ProductsService(db)
        svc.get = AsyncMock(return_value=existing)
        svc.repo.get_by_sku = AsyncMock(return_value=None)
        svc.repo.update = AsyncMock(side_effect=_fake_integrity("products_sku_key"))

        payload = ProductUpdate(sku="SKU-C")
        with pytest.raises(HTTPException) as exc_info:
            await svc.update(uuid4(), payload)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "DUPLICATE_SKU"
        db.rollback.assert_awaited_once()

    async def test_fk_violation_on_flush_is_422(self):
        existing = _product(category_id=uuid4())
        db = AsyncMock()
        svc = ProductsService(db)
        svc.get = AsyncMock(return_value=existing)
        svc._category_exists = AsyncMock(return_value=True)
        svc.repo.update = AsyncMock(
            side_effect=_fake_integrity("products_category_id_fkey")
        )

        payload = ProductUpdate(category_id=uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await svc.update(uuid4(), payload)
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_CATEGORY"
        db.rollback.assert_awaited_once()


class TestCategoryRace:
    async def test_create_duplicate_name_on_flush_is_409(self):
        db = AsyncMock()
        svc = CategoriesService(db)
        svc.repo.get_by_name = AsyncMock(return_value=None)
        svc.repo.create = AsyncMock(side_effect=_fake_integrity("categories_name_key"))

        with pytest.raises(HTTPException) as exc_info:
            await svc.create(CategoryCreate(name="Electronics"))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "DUPLICATE_CATEGORY"
        db.rollback.assert_awaited_once()

    async def test_update_duplicate_name_on_flush_is_409(self):
        existing = _category(name="Old Name")
        db = AsyncMock()
        svc = CategoriesService(db)
        svc.get = AsyncMock(return_value=existing)
        svc.repo.get_by_name = AsyncMock(return_value=None)
        svc.repo.update = AsyncMock(side_effect=_fake_integrity("categories_name_key"))

        with pytest.raises(HTTPException) as exc_info:
            await svc.update(uuid4(), CategoryUpdate(name="New Name"))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "DUPLICATE_CATEGORY"
        db.rollback.assert_awaited_once()
