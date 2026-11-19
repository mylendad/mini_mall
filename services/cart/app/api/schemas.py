"""Pydantic-схемы корзины (задача 4.1).

Запросы валидируются на границе API: UUID и количества — строгие типы,
невалидные значения отклоняются FastAPI с кодом 422 (в конверте
``ErrorResponse`` через обработчик ``RequestValidationError``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.config import settings


class AddItemRequest(BaseModel):
    """Тело ``POST /cart/items``: продукт и количество (>= 1)."""

    product_id: UUID
    quantity: int = Field(
        default=1, ge=1, le=settings.max_quantity, description="Количество (1..max)"
    )


class UpdateItemRequest(BaseModel):
    """Тело ``PATCH /cart/items/{product_id}``: абсолютное количество."""

    quantity: int = Field(ge=1, le=settings.max_quantity, description="Количество (1..max)")


class CartItemResponse(BaseModel):
    """Строка корзины: только ``product_id``, ``quantity``, ``added_at`` (D5)."""

    model_config = ConfigDict(from_attributes=True)

    product_id: UUID
    quantity: int
    added_at: datetime


class CartResponse(BaseModel):
    """Корзина пользователя (ответы GET/POST/PATCH)."""

    user_id: UUID
    items: list[CartItemResponse]


class ClearResponse(BaseModel):
    """Ответ ``DELETE /cart`` (успешные мутации возвращают состояние корзины)."""

    user_id: UUID
    items: list[CartItemResponse]
