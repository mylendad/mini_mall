"""Юнит-тесты use cases (задача 2.2) с in-memory фейком репозитория.

Фейк воспроизводит контракт хранилища: атомарные мутации, лимит различных
товаров, ``CartItemNotFound`` для отсутствующих товаров, TTL-семантика
(хранится, но не эмулируется по времени — TTL проверяется на реальном Redis).
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.application.protocols import (
    CartItemNotFound,
    CatalogUnavailable,
    ProductInactive,
    ProductNotFound,
    ProductStatus,
)
from app.application.use_cases import CartUseCases
from app.domain.cart import Cart, CartItem, CartLimitExceeded, QuantityOutOfBounds

U1 = uuid.uuid4()
P1 = uuid.uuid4()
P2 = uuid.uuid4()


class FakeCartRepository:
    """In-memory репозиторий с семантикой Redis-репозитория (3.1)."""

    def __init__(self, max_distinct_items: int = 5) -> None:
        self._items: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
        self.max_distinct_items = max_distinct_items

    def _items_of(self, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
        return self._items.setdefault(user_id, {})

    def _cart(self, user_id: uuid.UUID) -> Cart:
        items = {
            pid: CartItem(product_id=pid, quantity=q, added_at=datetime.now(UTC))
            for pid, q in self._items_of(user_id).items()
        }
        return Cart(user_id=user_id, items=items)

    async def get(self, user_id: uuid.UUID) -> Cart:
        return self._cart(user_id)

    async def add_item(
        self, user_id: uuid.UUID, product_id: uuid.UUID, quantity: int
    ) -> Cart:
        items = self._items_of(user_id)
        if product_id not in items and len(items) >= self.max_distinct_items:
            raise CartLimitExceeded("cart limit reached")
        items[product_id] = items.get(product_id, 0) + quantity
        return self._cart(user_id)

    async def set_quantity(
        self, user_id: uuid.UUID, product_id: uuid.UUID, quantity: int
    ) -> Cart:
        items = self._items_of(user_id)
        if product_id not in items:
            raise CartItemNotFound(str(product_id))
        items[product_id] = quantity
        return self._cart(user_id)

    async def remove_item(self, user_id: uuid.UUID, product_id: uuid.UUID) -> Cart:
        items = self._items_of(user_id)
        if product_id not in items:
            raise CartItemNotFound(str(product_id))
        del items[product_id]
        return self._cart(user_id)

    async def clear(self, user_id: uuid.UUID) -> Cart:
        self._items[user_id] = {}
        return self._cart(user_id)


class FakeCatalog:
    """Фейковый шлюз Catalog с настраиваемым ответом/сбоем."""

    def __init__(self, status: str = ProductStatus.ACTIVE) -> None:
        self.status = status
        self.calls: list[uuid.UUID] = []

    async def validate_product(self, product_id: uuid.UUID) -> str:
        self.calls.append(product_id)
        if self.status == "unavailable":
            raise CatalogUnavailable("catalog down")
        return self.status


@pytest.fixture
def repo() -> FakeCartRepository:
    return FakeCartRepository(max_distinct_items=2)


@pytest.fixture
def use_cases(repo: FakeCartRepository) -> CartUseCases:
    return CartUseCases(repo)


async def test_get_missing_cart_returns_empty(use_cases: CartUseCases):
    cart = await use_cases.get_cart(U1)
    assert cart.is_empty
    assert cart.user_id == U1


async def test_add_then_get(use_cases: CartUseCases):
    await use_cases.add_item(U1, P1, 2)
    cart = await use_cases.get_cart(U1)
    assert cart.items[P1].quantity == 2


async def test_idempotent_add_increments_quantity(use_cases: CartUseCases):
    await use_cases.add_item(U1, P1, 1)
    cart = await use_cases.add_item(U1, P1, 1)
    assert len(cart.items) == 1
    assert cart.items[P1].quantity == 2


async def test_add_validates_quantity_bounds(use_cases: CartUseCases):
    with pytest.raises(QuantityOutOfBounds):
        await use_cases.add_item(U1, P1, 0)
    with pytest.raises(QuantityOutOfBounds):
        await use_cases.add_item(U1, P1, 101)


async def test_add_respects_cart_limit(use_cases: CartUseCases):
    await use_cases.add_item(U1, P1, 1)
    await use_cases.add_item(U1, P2, 1)
    with pytest.raises(CartLimitExceeded):
        await use_cases.add_item(U1, uuid.uuid4(), 1)
    assert len((await use_cases.get_cart(U1)).items) == 2


async def test_set_quantity(use_cases: CartUseCases):
    await use_cases.add_item(U1, P1, 1)
    cart = await use_cases.set_quantity(U1, P1, 7)
    assert cart.items[P1].quantity == 7


async def test_set_quantity_missing_item_404(use_cases: CartUseCases):
    with pytest.raises(CartItemNotFound):
        await use_cases.set_quantity(U1, P1, 1)


async def test_remove_item(use_cases: CartUseCases):
    await use_cases.add_item(U1, P1, 1)
    cart = await use_cases.remove_item(U1, P1)
    assert cart.is_empty


async def test_remove_missing_item_404(use_cases: CartUseCases):
    with pytest.raises(CartItemNotFound):
        await use_cases.remove_item(U1, P1)


async def test_clear_cart(use_cases: CartUseCases):
    await use_cases.add_item(U1, P1, 1)
    cart = await use_cases.clear_cart(U1)
    assert cart.is_empty


async def test_add_with_catalog_validates_product(use_cases: CartUseCases):
    catalog = FakeCatalog(ProductStatus.ACTIVE)
    await use_cases.add_item(U1, P1, 1, catalog=catalog)
    assert catalog.calls == [P1]
    assert P1 in (await use_cases.get_cart(U1)).items


async def test_add_missing_product_rejected_cart_unchanged(
    use_cases: CartUseCases,
):
    catalog = FakeCatalog(ProductStatus.MISSING)
    with pytest.raises(ProductNotFound):
        await use_cases.add_item(U1, P1, 1, catalog=catalog)
    assert (await use_cases.get_cart(U1)).is_empty


async def test_add_inactive_product_rejected_cart_unchanged(
    use_cases: CartUseCases,
):
    catalog = FakeCatalog(ProductStatus.INACTIVE)
    with pytest.raises(ProductInactive):
        await use_cases.add_item(U1, P1, 1, catalog=catalog)
    assert (await use_cases.get_cart(U1)).is_empty


async def test_add_catalog_unavailable_rejected(use_cases: CartUseCases):
    catalog = FakeCatalog("unavailable")
    with pytest.raises(CatalogUnavailable):
        await use_cases.add_item(U1, P1, 1, catalog=catalog)
    assert (await use_cases.get_cart(U1)).is_empty


async def test_other_operations_do_not_touch_catalog(use_cases: CartUseCases):
    catalog = FakeCatalog("unavailable")
    await use_cases.add_item(U1, P1, 1)  # без шлюза
    await use_cases.set_quantity(U1, P1, 2)
    await use_cases.remove_item(U1, P1)
    await use_cases.clear_cart(U1)
    assert catalog.calls == []
