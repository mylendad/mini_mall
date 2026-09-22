"""Вспомогательные функции и маппер ошибок каталога.

Формат ответа об ошибке задан в ``common.errors``::

    {
        "error": {"code": "...", "message": "...", "details": null},
        "request_id": "..."
    }

:func:`error_detail` собирает только блок ``error``; ``request_id`` добавляется
глобальным обработчиком исключений в ``app.main`` из ``request.state``.
"""

from __future__ import annotations

from common.errors import ErrorDetail
from sqlalchemy.exc import IntegrityError


def error_detail(code: str, message: str, details: dict | None = None) -> dict:
    """Собирает блок ``error`` стандартного ответа об ошибке.

    Параметры:
        code: Машинный код ошибки (например, ``DUPLICATE_SKU``).
        message: Человекочитаемое сообщение.
        details: Дополнительный контекст (опционально).

    Возвращает:
        Словарь формата :class:`common.errors.ErrorDetail`.
    """
    return ErrorDetail(code=code, message=message, details=details).model_dump()


class IntegrityErrorMapper:
    """Переводит :class:`sqlalchemy.exc.IntegrityError` в коды ``ErrorResponse``.

    PostgreSQL-ограничения — единственный надёжный backstop для конкурентных
    дублей; маппер извлекает имя ограничения из диага ошибки и возвращает
    словарь :func:`error_detail` либо ``None`` (если ограничение не распознано).
    """

    CATEGORY_NAME_KEY = "categories_name_key"
    PRODUCT_SKU_KEY = "products_sku_key"
    PRODUCT_CATEGORY_FK = "products_category_id_fkey"

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

    def category_write(self, exc: IntegrityError) -> dict | None:
        """Дублирующее имя категории -> ``409 DUPLICATE_CATEGORY``."""
        if self._constraint_name(exc) == self.CATEGORY_NAME_KEY:
            return error_detail("DUPLICATE_CATEGORY", "Category name already exists")
        return None

    def product_write(self, exc: IntegrityError) -> dict | None:
        """Продукт: дубль SKU -> ``409 DUPLICATE_SKU``; FK на категорию -> ``422 INVALID_CATEGORY``."""
        name = self._constraint_name(exc)
        if name == self.PRODUCT_SKU_KEY:
            return error_detail("DUPLICATE_SKU", "Product SKU already exists")
        if name == self.PRODUCT_CATEGORY_FK:
            return error_detail("INVALID_CATEGORY", "Category does not exist")
        return None

    def category_delete(self, exc: IntegrityError) -> dict | None:
        """Удаление категории с продуктами (FK RESTRICT) -> ``409 CATEGORY_HAS_PRODUCTS``."""
        if self._constraint_name(exc) == self.PRODUCT_CATEGORY_FK:
            return error_detail(
                "CATEGORY_HAS_PRODUCTS", "Category has products and cannot be deleted"
            )
        return None
