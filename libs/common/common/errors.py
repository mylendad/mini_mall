"""Стандартные модели ошибок API.

Единый формат ответа об ошибке для всех сервисов::

    {
        "error": {"code": "...", "message": "...", "details": null},
        "request_id": "..."
    }
"""
from typing import Any

from pydantic import BaseModel


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
