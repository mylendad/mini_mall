"""Pydantic-схемы запросов и ответов инвентаря.

Валидация выполняется на границе API: количества (>= 0), quantity резерва
(> 0), порог low-stock (>= 0), непустой SKU. ``available`` — производное
поле (``on_hand - reserved``), вычисляется при сериализации.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SKU_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$"


class StockItemCreate(BaseModel):
    """Запрос создания складской позиции.

    Атрибуты:
        sku: Уникальный артикул.
        quantity_on_hand: Начальное физическое количество (>= 0).
        low_stock_threshold: Порог low-stock (>= 0, ``0`` — выключен).
        catalog_product_id: Необязательная ссылка на продукт каталога.
    """

    sku: str = Field(..., min_length=1, max_length=64, pattern=_SKU_PATTERN)
    quantity_on_hand: int = Field(..., ge=0)
    low_stock_threshold: int = Field(default=0, ge=0)
    catalog_product_id: uuid.UUID | None = None

    @field_validator("sku")
    @classmethod
    def _strip_sku(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("sku must not be empty")
        return v


class StockItemAdjust(BaseModel):
    """Запрос корректировки складской позиции (приёмка/исправление).

    Атрибуты:
        delta: Изменение физического количества (может быть отрицательным,
            итоговое ``quantity_on_hand`` не может стать отрицательным).
        reason: Причина корректировки (для аудита и payload события).
    """

    delta: int
    reason: str = Field(..., min_length=1, max_length=255)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason must not be empty")
        return v


class StockItemThresholdUpdate(BaseModel):
    """Запрос обновления порога low-stock (>= 0; ``0`` — выключен)."""

    low_stock_threshold: int = Field(..., ge=0)


class StockItemResponse(BaseModel):
    """Складская позиция в ответах API; ``available`` — производное поле."""

    id: uuid.UUID
    catalog_product_id: uuid.UUID | None
    sku: str
    quantity_on_hand: int
    quantity_reserved: int
    available: int
    low_stock_threshold: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockItemListResponse(BaseModel):
    """Пагинированный список складских позиций."""

    total: int
    limit: int
    offset: int
    items: list[StockItemResponse]


class AvailabilityResponse(BaseModel):
    """Доступность одного SKU."""

    sku: str
    quantity_on_hand: int
    quantity_reserved: int
    available: int
    in_stock: bool

    @classmethod
    def build(cls, *, sku: str, on_hand: int, reserved: int) -> "AvailabilityResponse":
        """Собирает ответ с производными ``available`` и ``in_stock``."""
        available = on_hand - reserved
        return cls(
            sku=sku,
            quantity_on_hand=on_hand,
            quantity_reserved=reserved,
            available=available,
            in_stock=available > 0,
        )


class AvailabilityBatchRequest(BaseModel):
    """Запрос пакетной проверки доступности: до ``max_skus`` SKU."""

    skus: list[str] = Field(..., min_length=1)

    @field_validator("skus")
    @classmethod
    def _strip_skus(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v]
        if any(not s for s in cleaned):
            raise ValueError("sku must not be empty")
        return cleaned


class AvailabilityBatchItem(BaseModel):
    """Результат пакетной проверки для одного SKU.

    ``found == False`` означает, что SKU не существует (запрос в целом
    всё равно успешен — пакет не «падает» из-за одного неизвестного SKU).
    """

    sku: str
    found: bool
    quantity_on_hand: int = 0
    quantity_reserved: int = 0
    available: int = 0
    in_stock: bool = False


class AvailabilityBatchResponse(BaseModel):
    """Ответ пакетной проверки: по элементу на каждый запрошенный SKU."""

    items: list[AvailabilityBatchItem]


class ReservationCreate(BaseModel):
    """Запрос создания резерва.

    Атрибуты:
        sku: Артикул.
        quantity: Количество (> 0).
        holder_ref: Ссылка на владельца (например, id заказа или корзины).
        ttl_seconds: TTL резерва; ``None`` — значение из настроек сервиса.
    """

    sku: str = Field(..., min_length=1, max_length=64, pattern=_SKU_PATTERN)
    quantity: int = Field(..., gt=0)
    holder_ref: str = Field(..., min_length=1, max_length=255)
    ttl_seconds: int | None = Field(default=None, gt=0)


class ReservationResponse(BaseModel):
    """Резерв в ответах API."""

    id: uuid.UUID
    stock_item_id: uuid.UUID
    quantity: int
    status: str
    holder_ref: str | None
    idempotency_key: str | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
