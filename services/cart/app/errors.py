"""Маппинг ошибок cart-сервиса (задача 3.3).

Формат ответа задан в ``common.errors`` (``ErrorResponse``/``error_detail``).
Коды, специфичные для корзин, объявлены здесь с той же структурой
«код ↔ статус ↔ сообщение», что и :class:`common.errors.ErrorCode`,
поскольку ``libs/common`` в этом изменении не расширяется (design D7).

Соответствия:
    - Catalog недоступен (таймаут/сбой/breaker) -> 503 ``CATALOG_UNAVAILABLE``;
    - продукт не найден -> 404 ``PRODUCT_NOT_FOUND``;
    - продукт неактивен -> 422 ``PRODUCT_INACTIVE``;
    - Redis недоступен -> 503 ``CART_STORAGE_UNAVAILABLE``;
    - товар отсутствует в корзине -> 404 ``CART_ITEM_NOT_FOUND``;
    - лимит различных товаров -> 409 ``CART_ITEM_LIMIT``;
    - границы количества -> 422 ``QUANTITY_OUT_OF_BOUNDS``;
    - нет/битый заголовок ``X-User-ID`` -> 401 ``MISSING_USER_CONTEXT`` /
      ``INVALID_USER_CONTEXT`` (коды из ``common.errors``).
"""

from __future__ import annotations

from enum import StrEnum
from http import HTTPStatus

from common.errors import UNPROCESSABLE, ErrorCode, error_detail

from app.application.protocols import (
    CartItemNotFound,
    CartStorageUnavailable,
    CatalogUnavailable,
    ProductInactive,
    ProductNotFound,
)
from app.domain.cart import CartLimitExceeded, QuantityOutOfBounds


class CartErrorCode(StrEnum):
    """Коды ошибок корзин с привязанным HTTP-статусом и сообщением.

    Атрибуты (как у :class:`common.errors.ErrorCode`):
        status_code: HTTP-статус ответа.
        message: Сообщение по умолчанию.
    """

    status_code: HTTPStatus
    message: str

    def __new__(cls, code: str, status_code: HTTPStatus, message: str):
        obj = str.__new__(cls, code)
        obj._value_ = code
        obj.status_code = status_code
        obj.message = message
        return obj

    CATALOG_UNAVAILABLE = (
        "CATALOG_UNAVAILABLE",
        HTTPStatus.SERVICE_UNAVAILABLE,
        "Catalog is temporarily unavailable",
    )
    PRODUCT_INACTIVE = (
        "PRODUCT_INACTIVE",
        UNPROCESSABLE,
        "Product is not active",
    )
    CART_ITEM_NOT_FOUND = (
        "CART_ITEM_NOT_FOUND",
        HTTPStatus.NOT_FOUND,
        "Item not found in cart",
    )
    CART_ITEM_LIMIT = (
        "CART_ITEM_LIMIT",
        HTTPStatus.CONFLICT,
        "Cart already holds the maximum number of distinct items",
    )
    QUANTITY_OUT_OF_BOUNDS = (
        "QUANTITY_OUT_OF_BOUNDS",
        UNPROCESSABLE,
        "Quantity must be between 1 and the configured maximum",
    )
    CART_STORAGE_UNAVAILABLE = (
        "CART_STORAGE_UNAVAILABLE",
        HTTPStatus.SERVICE_UNAVAILABLE,
        "Cart storage is temporarily unavailable",
    )


def cart_error_detail(code: CartErrorCode | ErrorCode) -> dict:
    """Собирает блок ``error`` стандартного конверта для кода корзины.

    Оборачивает :func:`common.errors.error_detail`: код используется как
    машинная строка, а сообщение берётся из атрибута ``message`` кода.
    """
    return error_detail(str(code), message=code.message)


def map_exception(exc: Exception) -> tuple[int, dict] | None:
    """Переводит исключения домена/приложения/инфраструктуры в (статус, error).

    Возвращает ``None`` для неизвестных исключений — их обработает
    глобальный 500-обработчик приложения.
    """
    if isinstance(exc, QuantityOutOfBounds):
        return UNPROCESSABLE, cart_error_detail(CartErrorCode.QUANTITY_OUT_OF_BOUNDS)
    if isinstance(exc, CartLimitExceeded):
        return (
            HTTPStatus.CONFLICT,
            cart_error_detail(CartErrorCode.CART_ITEM_LIMIT),
        )
    if isinstance(exc, CartItemNotFound):
        return (
            HTTPStatus.NOT_FOUND,
            cart_error_detail(CartErrorCode.CART_ITEM_NOT_FOUND),
        )
    if isinstance(exc, ProductNotFound):
        return (
            HTTPStatus.NOT_FOUND,
            cart_error_detail(ErrorCode.PRODUCT_NOT_FOUND),
        )
    if isinstance(exc, ProductInactive):
        return UNPROCESSABLE, cart_error_detail(CartErrorCode.PRODUCT_INACTIVE)
    if isinstance(exc, CatalogUnavailable):
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            cart_error_detail(CartErrorCode.CATALOG_UNAVAILABLE),
        )
    if isinstance(exc, CartStorageUnavailable):
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            cart_error_detail(CartErrorCode.CART_STORAGE_UNAVAILABLE),
        )
    return None
