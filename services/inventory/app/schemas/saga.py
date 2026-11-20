"""Pydantic-схемы команд саги (checkout-участие инвентаря).

Команды публикует Saga Orchestrator (Order Service) в командный топик
``inventory.commands``. Команды: ``reserve`` (заказ начался), ``confirm``
(заказ успешен), ``release`` (компенсация: заказ отменён или следующий шаг
саги упал). Обработчик идемпотентен по ``event_id`` события.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

CommandName = Literal["reserve", "confirm", "release"]


class SagaItem(BaseModel):
    """Позиция команды: один резерв на (заказ, SKU)."""

    sku: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., gt=0)


class SagaCommand(BaseModel):
    """Команда саги для инвентаря.

    Атрибуты:
        command: Тип команды (``reserve``/``confirm``/``release``).
        order_id: Идентификатор заказа (используется как ``holder_ref``).
        items: Позиции заказа (sku + quantity).
        saga_ref: Ссылка на экземпляр саги (для наблюдаемости).
        correlation_id: Сквозной идентификатор корреляции.
    """

    command: CommandName
    order_id: str = Field(..., min_length=1, max_length=255)
    items: list[SagaItem] = Field(..., min_length=1)
    saga_ref: str | None = None
    correlation_id: uuid.UUID | None = None


def parse_command(payload: dict) -> SagaCommand:
    """Разбирает payload команды.

    Исключения:
        ValidationError: команда некорректна (неизвестный тип команды,
            пустые items, quantity <= 0 и т.п.).
    """
    return SagaCommand.model_validate(payload)
