"""Юнит-тесты маппинга ошибок (задача 3.3): каждая ошибка -> код и статус."""

from common.errors import ErrorCode

from app.application.protocols import (
    CartItemNotFound,
    CartStorageUnavailable,
    CatalogUnavailable,
    ProductInactive,
    ProductNotFound,
)
from app.domain.cart import CartLimitExceeded, QuantityOutOfBounds
from app.errors import CartErrorCode, map_exception


def test_quantity_bounds_maps_to_422():
    status, error = map_exception(QuantityOutOfBounds("bad quantity"))
    assert status == 422
    assert error["code"] == CartErrorCode.QUANTITY_OUT_OF_BOUNDS
    assert error["message"]


def test_cart_limit_maps_to_409():
    status, error = map_exception(CartLimitExceeded("limit"))
    assert status == 409
    assert error["code"] == CartErrorCode.CART_ITEM_LIMIT


def test_cart_item_missing_maps_to_404():
    status, error = map_exception(CartItemNotFound("no item"))
    assert status == 404
    assert error["code"] == CartErrorCode.CART_ITEM_NOT_FOUND


def test_product_missing_maps_to_404():
    status, error = map_exception(ProductNotFound("no product"))
    assert status == 404
    assert error["code"] == ErrorCode.PRODUCT_NOT_FOUND


def test_product_inactive_maps_to_422():
    status, error = map_exception(ProductInactive("inactive"))
    assert status == 422
    assert error["code"] == CartErrorCode.PRODUCT_INACTIVE


def test_catalog_unavailable_maps_to_503():
    status, error = map_exception(CatalogUnavailable("catalog down"))
    assert status == 503
    assert error["code"] == CartErrorCode.CATALOG_UNAVAILABLE


def test_redis_down_maps_to_503():
    status, error = map_exception(CartStorageUnavailable("redis down"))
    assert status == 503
    assert error["code"] == CartErrorCode.CART_STORAGE_UNAVAILABLE


def test_unknown_exception_not_mapped():
    assert map_exception(RuntimeError("boom")) is None


def test_cart_codes_have_consistent_status_message():
    for code in CartErrorCode:
        assert isinstance(code.status_code, int)
        assert code.message
