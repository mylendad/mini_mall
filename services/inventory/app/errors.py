"""Маппер ошибок инвентаря.

Формат ответа и каталог кодов заданы в ``common.errors``; здесь только
перевод ошибок БД в коды этого сервиса. Блок ``error`` собирает общий
:func:`common.errors.error_detail`, а ``request_id`` добавляется глобальным
обработчиком исключений в ``app.main`` из ``request.state``.
"""

from __future__ import annotations

from common.errors import ErrorCode, error_detail
from sqlalchemy.exc import IntegrityError


class IntegrityErrorMapper:
    """Переводит :class:`sqlalchemy.exc.IntegrityError` в коды ``ErrorResponse``.

    PostgreSQL-ограничения — единственный надёжный backstop для конкурентных
    дублей; маппер извлекает имя ограничения из диага ошибки и возвращает
    словарь :func:`common.errors.error_detail` либо ``None`` (если ограничение
    не распознано).
    """

    STOCK_ITEM_SKU_KEY = "stock_items_sku_key"
    RESERVATION_IDEMPOTENCY_KEY = "reservations_idempotency_key_key"

    @staticmethod
    def _constraint_name(exc: IntegrityError) -> str | None:
        """Обходит ``__cause__``/``__context__``/``orig`` в поисках имени ограничения.

        Псевдоним ``diag.constraint_name`` (psycopg2), ``constraint_name``
        напрямую (raw asyncpg), либо ``__cause__``-обёртка SQLAlchemy.
        """
        cur = exc
        for _ in range(6):
            if cur is None:
                return None
            diag = getattr(cur, "diag", None)
            name = getattr(diag, "constraint_name", None)
            if name:
                return name
            name = getattr(cur, "constraint_name", None)
            if name:
                return name
            cur = (
                getattr(cur, "__cause__", None)
                or getattr(cur, "__context__", None)
                or getattr(cur, "orig", None)
            )
        return None

    def stock_item_write(self, exc: IntegrityError) -> dict | None:
        """Дублирующий SKU склада -> ``409 DUPLICATE_SKU`` с сообщением инвентаря."""
        if self._constraint_name(exc) == self.STOCK_ITEM_SKU_KEY:
            return error_detail(
                ErrorCode.DUPLICATE_SKU, "Stock item SKU already exists"
            )
        return None

    def reservation_write(self, exc: IntegrityError) -> dict | None:
        """Дубликат идемпотентного ключа резерва -> ``DUPLICATE_SKU`` с сообщением."""
        if self._constraint_name(exc) == self.RESERVATION_IDEMPOTENCY_KEY:
            return error_detail(
                ErrorCode.DUPLICATE_SKU, "Reservation idempotency key already exists"
            )
        return None
