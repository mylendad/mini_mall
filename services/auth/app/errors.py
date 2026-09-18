"""Вспомогательные функции для единого формата ошибок API.

Формат ответа об ошибке задан в ``common.errors``::

    {
        "error": {"code": "...", "message": "...", "details": null},
        "request_id": "..."
    }

Функция :func:`error_detail` собирает только блок ``error``; ``request_id``
добавляется глобальным обработчиком исключений в ``app.main`` из
``request.state.request_id``.
"""
from common.errors import ErrorDetail


def error_detail(code: str, message: str, details: dict | None = None) -> dict:
    """Собирает блок ``error`` стандартного ответа об ошибке.

    Параметры:
        code: Машинный код ошибки (например, ``DUPLICATE_EMAIL``).
        message: Человекочитаемое сообщение.
        details: Дополнительный контекст (опционально).

    Возвращает:
        Словарь формата :class:`common.errors.ErrorDetail`.
    """
    return ErrorDetail(code=code, message=message, details=details).model_dump()