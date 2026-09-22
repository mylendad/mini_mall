"""Pydantic-схемы запросов и ответов каталога.

Валидация выполняется на границе API: UUID, цены (``Decimal``, > 0, до 2
знаков), ISO-4217 валюту, SKU, атрибуты (JSONB) и фильтры. Цена сериализуется
строкой — без потери точности ``Numeric(12,2)``.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CategoryCreate(BaseModel):
    """Запрос создания категории.

    Атрибуты:
        name: Уникальное имя (обрезается по краям, непустое).
        description: Необязательное описание.
    """

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class CategoryUpdate(BaseModel):
    """Запрос обновления категории (все поля опциональны)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class CategoryResponse(BaseModel):
    """Категория в ответах API."""

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


_SKU_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$"
_CURRENCY_PATTERN = r"^[A-Z]{3}$"


class ProductBase(BaseModel):
    """Общие поля продукта (создание и обновление)."""

    category_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(..., pattern=_CURRENCY_PATTERN)
    sku: str = Field(..., min_length=1, max_length=64, pattern=_SKU_PATTERN)
    attributes: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class ProductCreate(ProductBase):
    """Запрос создания продукта."""


class ProductUpdate(BaseModel):
    """Запрос обновления продукта (все поля опциональны).

    ``None`` значения означают «не менять»; атрибуты заменяются целиком.
    """

    category_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, pattern=_CURRENCY_PATTERN)
    sku: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=_SKU_PATTERN
    )
    attributes: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class ProductResponse(BaseModel):
    """Продукт в ответах API (цена строкой)."""

    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    description: str | None
    price: str
    currency: str
    sku: str
    attributes: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("price", mode="before")
    @classmethod
    def _price_to_str(cls, v: Any) -> str:
        return str(v)


class ProductListResponse(BaseModel):
    """Пагинированный список продуктов."""

    total: int
    limit: int
    offset: int
    items: list[ProductResponse]


class ProductSearchResult(BaseModel):
    """Результат поиска: стабильный DTO, не сырой ``_source`` ES."""

    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    category_id: uuid.UUID
    category_name: str
    price: str
    currency: str
    attributes: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductSearchResponse(BaseModel):
    """Пагинированный ответ поиска с фасетами.

    ``facets`` — агрегации по отфильтрованному набору результатов (например,
    ``by_category`` c counts или ``price_ranges``), derived из результата.
    """

    total: int
    limit: int
    offset: int
    items: list[ProductSearchResult]
    facets: dict[str, Any] = Field(default_factory=dict)
