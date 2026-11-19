"""HTTP-клиент Catalog для валидации продукта (задача 3.2, design D4).

Синхронный (в рамках обработки запроса) вызов ``GET
/api/v1/products/{product_id}`` с явным таймаутом из настроек и circuit
breaker (``app.infrastructure.breaker``). Итог валидации:

    - ``200`` и ``is_active`` — ``ProductStatus.ACTIVE``;
    - ``200`` без ``is_active`` — ``ProductStatus.INACTIVE``;
    - ``404`` — ``ProductStatus.MISSING``;
    - таймаут/сеть/5xx/breaker — :class:`CatalogUnavailable` (-> 503).

Продукт не парсится целиком: корзина не хранит снимков имени/цены (D5).
"""

from __future__ import annotations

from uuid import UUID

import httpx
import structlog

from app.application.protocols import (
    CatalogUnavailable,
    ProductStatus,
)
from app.config import settings
from app.infrastructure.breaker import BreakerOpenError, CircuitBreaker, catalog_breaker

logger = structlog.get_logger()


class CatalogClient:
    """Реализация :class:`app.application.protocols.CatalogGateway` на httpx."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._client = client
        self._breaker = breaker if breaker is not None else catalog_breaker

    async def validate_product(self, product_id: UUID) -> str:
        """Валидирует продукт: found/active/missing или ``CatalogUnavailable``."""
        try:
            return await self._breaker.call(self._fetch, product_id)
        except BreakerOpenError as exc:
            logger.warning("catalog_breaker_open", product_id=str(product_id))
            raise CatalogUnavailable("catalog is temporarily unavailable") from exc
        except CatalogUnavailable:
            raise
        except Exception as exc:
            logger.warning("catalog_call_failed", error=str(exc))
            raise CatalogUnavailable("catalog is temporarily unavailable") from exc

    async def _fetch(self, product_id: UUID) -> str:
        """Сам HTTP-вызов; 404 -> ``MISSING``, неактивный -> ``INACTIVE``."""
        try:
            response = await self._client.get(
                f"/api/v1/products/{product_id}",
                timeout=settings.catalog_http_timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning("catalog_http_error", error=str(exc))
            raise CatalogUnavailable("catalog is temporarily unavailable") from exc
        if response.status_code == httpx.codes.NOT_FOUND:
            return ProductStatus.MISSING
        if response.is_error:
            logger.warning(
                "catalog_unexpected_status", status_code=response.status_code
            )
            raise CatalogUnavailable("catalog is temporarily unavailable")
        body = response.json()
        if body.get("is_active", False):
            return ProductStatus.ACTIVE
        return ProductStatus.INACTIVE
