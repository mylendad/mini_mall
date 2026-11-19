"""Домен корзины: сущности и чистые правила (без инфраструктуры).

Модуль не импортирует fastapi/redis/httpx — только стандартную библиотеку,
поэтому слой тестируется в изоляции (требование задачи 2.1).

Правила:
    - количество в границах ``1..max_quantity``;
    - максимум ``max_distinct_items`` различных товаров;
    - повторное добавление того же ``product_id`` увеличивает количество;
    - пустая корзина — отсутствие элементов (``items == {}``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID


class QuantityOutOfBounds(ValueError):
    """Количество вне границ ``1..max_quantity`` (-> 422)."""


class CartLimitExceeded(Exception):
    """Превышен максимум различных товаров в корзине (-> 409)."""


@dataclass(frozen=True)
class CartItem:
    """Строка корзины: только ``product_id``, ``quantity`` и ``added_at``.

    Снимков имени/цены нет по design D5: данные продукта читаются из Catalog
    в момент отображения корзины клиентом.
    """

    product_id: UUID
    quantity: int
    added_at: datetime

    def __post_init__(self) -> None:
        if not 1 <= self.quantity:
            raise QuantityOutOfBounds("quantity must be >= 1")


@dataclass
class Cart:
    """Корзина пользователя: товары по ``product_id`` без дублей.

    Атрибуты:
        user_id: владелец корзины (UUID из доверенного заголовка шлюза).
        items: словарь ``product_id -> CartItem`` (порядок вставки сохраняется).
    """

    user_id: UUID
    items: dict[UUID, CartItem] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Пустая корзина — нет элементов (ключ Redis может и не существовать)."""
        return not self.items

    def add(
        self,
        product_id: UUID,
        quantity: int,
        *,
        max_distinct_items: int,
        max_quantity: int,
        added_at: datetime | None = None,
    ) -> None:
        """Добавляет товар; для существующего — увеличивает количество.

        Чистая мутация in-place: границы количества и лимит различных товаров
        проверяются до изменения состояния, поэтому при отклонении корзина
        остаётся неизменной (409/422 оставляют корзину как была).
        """
        check_quantity(quantity, max_quantity)
        existing = self.items.get(product_id)
        if existing is None:
            if len(self.items) >= max_distinct_items:
                raise CartLimitExceeded(
                    "cart already holds the maximum number of distinct items"
                )
            self.items[product_id] = CartItem(
                product_id=product_id,
                quantity=quantity,
                added_at=added_at or datetime.now(UTC),
            )
        else:
            check_quantity(existing.quantity + quantity, max_quantity)
            self.items[product_id] = CartItem(
                product_id=product_id,
                quantity=existing.quantity + quantity,
                added_at=existing.added_at,
            )

    def set_quantity(
        self, product_id: UUID, quantity: int, *, max_quantity: int
    ) -> None:
        """Устанавливает абсолютное количество существующего товара."""
        if product_id not in self.items:
            raise KeyError(product_id)
        check_quantity(quantity, max_quantity)
        existing = self.items[product_id]
        self.items[product_id] = CartItem(
            product_id=product_id,
            quantity=quantity,
            added_at=existing.added_at,
        )

    def remove(self, product_id: UUID) -> None:
        """Удаляет товар; отсутствующий товар — ``KeyError`` (-> 404)."""
        if product_id not in self.items:
            raise KeyError(product_id)
        del self.items[product_id]

    def clear(self) -> None:
        """Полностью очищает корзину."""
        self.items.clear()


def check_quantity(quantity: int, max_quantity: int) -> None:
    """Проверяет границы количества ``1..max_quantity`` (-> 422)."""
    if not 1 <= quantity <= max_quantity:
        raise QuantityOutOfBounds(
            f"quantity must be between 1 and {max_quantity}"
        )
