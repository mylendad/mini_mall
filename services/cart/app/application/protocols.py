"""Порты приложения: протоколы репозитория корзины и шлюза Catalog.

Слой приложения зависит только от протоколов, а не от реализаций, поэтому
use cases тестируются с in-memory фейками (задача 2.2), а инфраструктура
(задачи 3.1/3.2) реализует их поверх Redis и httpx.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.cart import Cart


class CartItemNotFound(Exception):
    """Товар отсутствует в корзине (-> 404)."""


class ProductNotFound(Exception):
    """Catalog не знает такой продукт (-> 404)."""


class ProductInactive(Exception):
    """Продукт существует, но неактивен (-> 422)."""


class CatalogUnavailable(Exception):
    """Catalog недоступен (таймаут/сбой/breaker открыт) (-> 503)."""


class CartStorageUnavailable(Exception):
    """Redis недоступен (-> 503)."""


@runtime_checkable
class CartRepository(Protocol):
    """Порт хранилища корзин.

    Мутации атомарны на стороне хранилища (design D2): лимит различных
    товаров и TTL-обновление выполняются в том же атомарном юните, что и
    запись, поэтому конкурентные мутации не теряют обновлений. Методы
    бросают :class:`CartItemNotFound` / :class:`CartLimitExceeded`.
    """

    async def get(self, user_id: UUID) -> Cart:
        """Возвращает корзину; отсутствие ключа — пустая корзина."""
        ...

    async def add_item(
        self, user_id: UUID, product_id: UUID, quantity: int
    ) -> Cart:
        """Атомарно добавляет товар (HINCRBY для существующего) и обновляет TTL."""
        ...

    async def set_quantity(
        self, user_id: UUID, product_id: UUID, quantity: int
    ) -> Cart:
        """Атомарно задаёт абсолютное количество; отсутствие -> ``CartItemNotFound``."""
        ...

    async def remove_item(self, user_id: UUID, product_id: UUID) -> Cart:
        """Атомарно удаляет товар; отсутствие -> ``CartItemNotFound``."""
        ...

    async def clear(self, user_id: UUID) -> Cart:
        """Полностью очищает корзину."""
        ...


class ProductStatus:
    """Итог валидации продукта в Catalog (found/active/missing)."""

    ACTIVE = "active"
    MISSING = "missing"
    INACTIVE = "inactive"


class CatalogGateway(Protocol):
    """Порт валидации продукта через Catalog (вызывается только на добавление)."""

    async def validate_product(self, product_id: UUID) -> str:
        """Возвращает один из ``ProductStatus`` или бросает :class:`CatalogUnavailable`."""
        ...


def make_user_cart(user_id: UUID) -> Cart:
    """Фабрика пустой корзины владельца ``user_id`` (для тестов/фейков)."""
    return Cart(user_id=user_id, items={})
