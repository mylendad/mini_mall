"""Система каталога: модели категорий, продуктов и outbox-очереди.

Модели регистрируются в :attr:`app.database.Base.metadata`; таблицы создаются
исключительно миграциями Alembic (``alembic/versions/0001_initial.py``).
"""

from app.models.catalog import Category, Product
from app.models.outbox import IndexOutbox

__all__ = ["Category", "IndexOutbox", "Product"]
