"""SQLAlchemy-модели каталога: категории и продукты.

PostgreSQL — единственный источник истины каталога. Схема (таблицы,
ограничения, индексы) создаётся миграциями Alembic, никогда на старте
приложения. Цены хранятся как ``Numeric(12,2)`` и сериализуются строками,
атрибуты продуктов — ``JSONB`` (структурированные данные, не строки).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Category(Base):
    """Модель категории товаров.

    Атрибуты:
        id: UUID категории.
        name: Уникальное имя категории (индексировано).
        description: Необязательное описание.
        created_at: Время создания (UTC).
        updated_at: Время последнего обновления (UTC).
        products: Связанные продукты (RESTRICT при удалении).
    """

    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    products = relationship("Product", back_populates="category", passive_deletes=True)


class Product(Base):
    """Модель продукта.

    Атрибуты:
        id: UUID продукта.
        category_id: Категория (FK, ``ON DELETE RESTRICT`` — нельзя удалить
            категорию с продуктами).
        name: Имя продукта.
        description: Необязательное описание.
        price: Цена (``Numeric(12,2)``, > 0).
        currency: ISO-4217 код валюты (3 заглавные буквы).
        sku: Уникальный артикул (индексировано).
        attributes: Структурированные атрибуты (JSONB, по умолчанию ``{}``).
        is_active: Активен ли продукт (неактивные исключаются из поиска).
        created_at: Время создания (UTC).
        updated_at: Время последнего обновления (UTC).
        category: Связанная категория.
    """

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_products_price_positive"),
        CheckConstraint(
            r"currency ~ '^[A-Z]{3}$'", name="ck_products_currency_iso4217"
        ),
        Index("ix_products_category_id", "category_id"),
        Index("ix_products_sku", "sku", unique=True),
        Index("ix_products_is_active", "is_active", postgresql_where=text("is_active")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id = Column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    sku = Column(String(64), nullable=False)
    attributes = Column(JSONB, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    category = relationship("Category", back_populates="products")
