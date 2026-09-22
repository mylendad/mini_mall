"""Юнит-тесты маппера IntegrityError -> коды ошибок (8.1)."""

from types import SimpleNamespace

import sqlalchemy.exc as saexc

from app.errors import IntegrityErrorMapper, error_detail


def _fake_integrity(constraint_name: str | None) -> saexc.IntegrityError:
    orig = SimpleNamespace(diag=SimpleNamespace(constraint_name=constraint_name))
    return saexc.IntegrityError("stmt", {"params": {}}, orig)


def test_error_detail_shape():
    detail = error_detail("DUPLICATE_SKU", "duplicate", details={"sku": "X"})
    assert detail == {
        "code": "DUPLICATE_SKU",
        "message": "duplicate",
        "details": {"sku": "X"},
    }


def test_duplicate_category_mapped_to_409():
    mapper = IntegrityErrorMapper()
    mapped = mapper.category_write(_fake_integrity("categories_name_key"))
    assert mapped is not None and mapped["code"] == "DUPLICATE_CATEGORY"


def test_duplicate_sku_mapped_to_409():
    mapper = IntegrityErrorMapper()
    mapped = mapper.product_write(_fake_integrity("products_sku_key"))
    assert mapped is not None and mapped["code"] == "DUPLICATE_SKU"


def test_fk_violation_on_product_write_is_invalid_category():
    mapper = IntegrityErrorMapper()
    mapped = mapper.product_write(_fake_integrity("products_category_id_fkey"))
    assert mapped is not None and mapped["code"] == "INVALID_CATEGORY"


def test_fk_violation_on_category_delete_is_has_products():
    mapper = IntegrityErrorMapper()
    mapped = mapper.category_delete(_fake_integrity("products_category_id_fkey"))
    assert mapped is not None and mapped["code"] == "CATEGORY_HAS_PRODUCTS"


def test_unknown_constraint_is_not_mapped():
    mapper = IntegrityErrorMapper()
    assert mapper.product_write(_fake_integrity("some_other_constraint")) is None
    assert mapper.category_write(_fake_integrity("some_other_constraint")) is None


def test_missing_diag_is_not_mapped():
    mapper = IntegrityErrorMapper()
    orig = SimpleNamespace(diag=None)
    exc = saexc.IntegrityError("stmt", {}, orig)
    assert mapper.product_write(exc) is None
