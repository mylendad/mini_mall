"""Use cases корзины (задача 2.2).

Каждый use case работает против протокола
:class:`app.application.protocols.CartRepository`; валидация количества
выполняется чистым доменом (:mod:`app.domain.cart`), лимит различных
товаров и атомарность мутаций — на стороне хранилища. Catalog участвует
только в добавлении товара (design D4, fail-closed).

Ошибки домена/приложения (``QuantityOutOfBounds``, ``CartLimitExceeded``,
``CartItemNotFound``, ``ProductNotFound``, ``ProductInactive``,
``CatalogUnavailable``) маппятся в стандартный конверт ошибок в
``app.errors``; сырые исключения хранилища оборачиваются в
:class:`CartStorageUnavailable`.
"""

from __future__ import annotations

from uuid import UUID

from app.application.protocols import (
    CartRepository,
    CartStorageUnavailable,
    CatalogGateway,
    ProductInactive,
    ProductNotFound,
    ProductStatus,
)
from app.config import settings
from app.domain.cart import (
    Cart,
    CartLimitExceeded,
    QuantityOutOfBounds,
    check_quantity,
)


class CartUseCases:
    """Прикладные операции над корзиной пользователя."""

    def __init__(self, repository: CartRepository) -> None:
        self._repository = repository

    async def get_cart(self, user_id: UUID) -> Cart:
        """Возвращает корзину; отсутствующий ключ — пустая корзина (200)."""
        return await self._repository.get(user_id)

    async def add_item(
        self,
        user_id: UUID,
        product_id: UUID,
        quantity: int,
        catalog: CatalogGateway | None = None,
    ) -> Cart:
        """Добавляет товар (повторное добавление увеличивает количество).

        Порядок: границы количества (422), затем валидация продукта в
        Catalog (404/422/503 — корзина не изменяется), затем атомарная
        запись в хранилище (409 при лимите — корзина не изменяется).
        """
        check_quantity(quantity, settings.max_quantity)
        if catalog is not None:
            status = await catalog.validate_product(product_id)
            if status == ProductStatus.MISSING:
                raise ProductNotFound(str(product_id))
            if status == ProductStatus.INACTIVE:
                raise ProductInactive(str(product_id))
        return await self._repository.add_item(user_id, product_id, quantity)

    async def set_quantity(
        self, user_id: UUID, product_id: UUID, quantity: int
    ) -> Cart:
        """Задаёт абсолютное количество товара (404 — товара нет)."""
        check_quantity(quantity, settings.max_quantity)
        return await self._repository.set_quantity(user_id, product_id, quantity)

    async def remove_item(self, user_id: UUID, product_id: UUID) -> Cart:
        """Удаляет товар (404 — товара нет)."""
        return await self._repository.remove_item(user_id, product_id)

    async def clear_cart(self, user_id: UUID) -> Cart:
        """Полностью очищает корзину."""
        return await self._repository.clear(user_id)


__all__ = [
    "CartLimitExceeded",
    "CartStorageUnavailable",
    "CartUseCases",
    "QuantityOutOfBounds",
]
