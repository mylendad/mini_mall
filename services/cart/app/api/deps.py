"""Разрешение пользователя из доверенного заголовка шлюза (задача 4.2, D3).

API Gateway валидирует JWT и внедряет ``X-User-ID`` (UUID). Сервис проверяет
только наличие и формат заголовка: отсутствующий или не-UUID -> 401
(MISSING_USER_CONTEXT / INVALID_USER_CONTEXT из ``common.errors``).
Собственная аутентификация не реализуется — identity принадлежит шлюзу.
"""

from __future__ import annotations

from uuid import UUID

from common.errors import ErrorCode, error_detail
from fastapi import Header, HTTPException


async def get_user_id(
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> UUID:
    """Возвращает UUID владельца корзины или 401 в стандартном конверте."""
    if not x_user_id:
        raise HTTPException(
            status_code=401,
            detail=error_detail(ErrorCode.MISSING_USER_CONTEXT),
        )
    try:
        return UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail=error_detail(ErrorCode.INVALID_USER_CONTEXT),
        ) from exc
