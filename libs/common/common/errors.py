"""Стандартные модели ошибок API и единый каталог кодов.

Единый формат ответа об ошибке для всех сервисов::

    {
        "error": {"code": "...", "message": "...", "details": null},
        "request_id": "..."
    }

:class:`ErrorCode` — единственный источник истины для машинного кода ошибки,
связанного с ним HTTP-статуса и сообщения по умолчанию. Вызывающий код берёт
статус из ``ErrorCode.<X>.status_code`` вместо того, чтобы писать его руками
рядом с кодом, поэтому опечатка в коде невозможна, а перечень ошибок сервиса
находится одним ``rg ErrorCode``.

``message`` можно переопределить на месте, когда контекст ошибки требует
уточнения (например, ``INVALID_SORT`` подставляет сам ключ сортировки).
"""

from enum import StrEnum
from http import HTTPStatus
from typing import Any, Self

from pydantic import BaseModel

#: 422 до 3.13 называется ``UNPROCESSABLE_ENTITY``, после — ``UNPROCESSABLE_CONTENT``.
#: Явный алиас снимает зависимость от версии интерпретатора.
UNPROCESSABLE = HTTPStatus(422)


class ErrorDetail(BaseModel):
    """Детализированная информация об одной ошибке.

    Атрибуты:
        code: Машинный код ошибки (например, ``INVALID_CREDENTIALS``).
        message: Человекочитаемое сообщение об ошибке.
        details: Дополнительный контекст (опционально).
    """

    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Стандартный ответ API при ошибке.

    Атрибуты:
        error: Описание ошибки.
        request_id: Идентификатор запроса для трассировки.
    """

    error: ErrorDetail
    request_id: str


class ErrorCode(StrEnum):
    """Каталог кодов ошибок с привязанным статусом и сообщением.

    Значение элемента — строка кода, попадающая в поле ``error.code``; статус
    и сообщение хранятся рядом с ним, чтобы пара «код ↔ статус» не расходилась
    между вызывающими сайтами.
    """

    status_code: HTTPStatus
    message: str

    def __new__(cls, code: str, status_code: HTTPStatus, message: str) -> Self:
        obj = str.__new__(cls, code)
        obj._value_ = code
        obj.status_code = status_code
        obj.message = message
        return obj

    # Общие для сервисов.
    VALIDATION_ERROR = (
        "VALIDATION_ERROR",
        UNPROCESSABLE,
        "Request validation failed",
    )
    INTERNAL_ERROR = (
        "INTERNAL_ERROR",
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "Internal server error",
    )

    # auth-service.
    DUPLICATE_EMAIL = (
        "DUPLICATE_EMAIL",
        HTTPStatus.CONFLICT,
        "Email already registered",
    )
    INVALID_CREDENTIALS = (
        "INVALID_CREDENTIALS",
        HTTPStatus.UNAUTHORIZED,
        "Invalid email, password, or inactive user",
    )
    INVALID_REFRESH_TOKEN = (
        "INVALID_REFRESH_TOKEN",
        HTTPStatus.UNAUTHORIZED,
        "Refresh token not found",
    )
    TOKEN_REUSE_DETECTED = (
        "TOKEN_REUSE_DETECTED",
        HTTPStatus.UNAUTHORIZED,
        "Revoked token reuse detected. All tokens revoked.",
    )
    EXPIRED_REFRESH_TOKEN = (
        "EXPIRED_REFRESH_TOKEN",
        HTTPStatus.UNAUTHORIZED,
        "Refresh token expired",
    )
    INACTIVE_USER = (
        "INACTIVE_USER",
        HTTPStatus.UNAUTHORIZED,
        "User is inactive or not found",
    )
    INVALID_GATEWAY_SECRET = (
        "INVALID_GATEWAY_SECRET",
        HTTPStatus.UNAUTHORIZED,
        "X-Gateway-Secret header is invalid or missing",
    )
    MISSING_USER_CONTEXT = (
        "MISSING_USER_CONTEXT",
        HTTPStatus.UNAUTHORIZED,
        "X-User-ID and X-User-Roles headers are required",
    )
    INVALID_USER_CONTEXT = (
        "INVALID_USER_CONTEXT",
        HTTPStatus.UNAUTHORIZED,
        "X-User-ID header must contain a valid UUID",
    )
    USER_NOT_FOUND = (
        "USER_NOT_FOUND",
        HTTPStatus.UNAUTHORIZED,
        "User not found or inactive",
    )

    # catalog-service.
    FORBIDDEN = (
        "FORBIDDEN",
        HTTPStatus.FORBIDDEN,
        "Admin role required for reindex",
    )
    SEARCH_UNAVAILABLE = (
        "SEARCH_UNAVAILABLE",
        HTTPStatus.SERVICE_UNAVAILABLE,
        "Search is temporarily unavailable",
    )
    DUPLICATE_CATEGORY = (
        "DUPLICATE_CATEGORY",
        HTTPStatus.CONFLICT,
        "Category name already exists",
    )
    CATEGORY_NOT_FOUND = (
        "CATEGORY_NOT_FOUND",
        HTTPStatus.NOT_FOUND,
        "Category not found",
    )
    CATEGORY_HAS_PRODUCTS = (
        "CATEGORY_HAS_PRODUCTS",
        HTTPStatus.CONFLICT,
        "Category has products and cannot be deleted",
    )
    PRODUCT_NOT_FOUND = (
        "PRODUCT_NOT_FOUND",
        HTTPStatus.NOT_FOUND,
        "Product not found",
    )
    DUPLICATE_SKU = (
        "DUPLICATE_SKU",
        HTTPStatus.CONFLICT,
        "Product SKU already exists",
    )
    INVALID_CATEGORY = (
        "INVALID_CATEGORY",
        UNPROCESSABLE,
        "Category does not exist",
    )
    INVALID_SORT = (
        "INVALID_SORT",
        UNPROCESSABLE,
        "Unsupported sort key or order",
    )


#: Сквозной код для HTTPException, пришедших не из нашего кода (роутинг Starlette,
#: 404 и т. п.): статус и текст задаёт само исключение, поэтому связать его с
#: фиксированным HTTP-статусом нельзя и он намеренно не входит в ErrorCode.
HTTP_ERROR = "HTTP_ERROR"


def error_detail(
    code: ErrorCode | str, message: str | None = None, details: dict | None = None
) -> dict:
    """Собирает блок ``error`` стандартного ответа об ошибке.

    Параметры:
        code: Код из :class:`ErrorCode` (либо :data:`HTTP_ERROR`).
        message: Сообщение; по умолчанию берётся из ``code.message``, поэтому
            для ``HTTP_ERROR`` его нужно передать явно.
        details: Дополнительный контекст (опционально).

    Возвращает:
        Словарь формата :class:`ErrorDetail`, готовый для ``HTTPException.detail``.
    """
    default = code.message if isinstance(code, ErrorCode) else code
    return ErrorDetail(
        code=str(code), message=message or default, details=details
    ).model_dump()
