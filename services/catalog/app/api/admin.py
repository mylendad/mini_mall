"""Администативные эндпоинты каталога (полный реиндекс из PostgreSQL).

Авторизация (D7): каталог не реализует аутентификацию. Если присутствует
заголовок ``X-User-Roles`` (форма доверенного шлюза) и в нём нет роли
``admin`` — операция запрещена (403). Внутри платформенного trust-периметра
(шлюз ещё не построен) заголовок отсутствует, поэтому вне ``production``
гейт ``X-User-Roles`` не требуется; в ``production`` доступ без роли закрыт
(гейт по окружению), чтобы разрушающая операция не была публичной.
"""

from __future__ import annotations

from common.errors import ErrorDetail
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import elasticsearch as es
from app.config import settings
from app.database import get_db
from app.services.breaker import search_breaker
from app.services.indexer import reindex_all

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _is_admin(x_user_roles: str | None, *, environment: str) -> bool:
    """True, если роли переданы и содержат ``admin``.

    Без заголовка (внутри trust-периметра) доступ открыт только вне
    ``production``; в ``production`` роль обязательна.
    """
    if not x_user_roles:
        return environment != "production"
    return "admin" in {role.strip() for role in x_user_roles.split(",")}


@router.post("/reindex")
async def reindex(
    db: AsyncSession = Depends(get_db),
    x_user_roles: str | None = Header(default=None, alias="X-User-Roles"),
) -> dict:
    """Перестраивает индекс ``catalog_products_v1`` из PostgreSQL.

    Удаляет индекс (старые документы исчезают — сходимость), создаёт заново
    с mapping по D5 и пакетно переиндексирует все продукты. Административная
    операция: ``admin`` в ``X-User-Roles``, либо открытая внутри trust-периметра
    вне ``production`` (D7).
    """
    if not _is_admin(x_user_roles, environment=settings.environment):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorDetail(
                code="FORBIDDEN",
                message="Admin role required for reindex",
                details=None,
            ).model_dump(),
        )
    try:
        reindexed = await search_breaker.call(reindex_all, es.es_client, db)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ErrorDetail(
                code="SEARCH_UNAVAILABLE",
                message="Index unavailable",
                details={"reason": str(exc)},
            ).model_dump(),
        ) from exc
    return {"index": es.CATALOG_INDEX, "reindexed": reindexed}
