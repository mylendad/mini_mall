"""Юнит-тесты домена корзины (задача 2.1): границы, дубли, лимит."""

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.cart import (
    Cart,
    CartItem,
    CartLimitExceeded,
    QuantityOutOfBounds,
    check_quantity,
)

U1 = uuid.uuid4()
U2 = uuid.uuid4()
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_add_new_item():
    cart = Cart(user_id=U1)
    cart.add(U2, 2, max_distinct_items=5, max_quantity=10, added_at=NOW)

    assert not cart.is_empty
    item = cart.items[U2]
    assert item.quantity == 2
    assert item.added_at == NOW


def test_add_duplicate_increases_quantity_and_keeps_added_at():
    cart = Cart(user_id=U1)
    cart.add(U2, 1, max_distinct_items=5, max_quantity=10, added_at=NOW)
    cart.add(U2, 4, max_distinct_items=5, max_quantity=10)

    assert len(cart.items) == 1
    assert cart.items[U2].quantity == 5
    assert cart.items[U2].added_at == NOW


def test_add_quantity_zero_rejected():
    cart = Cart(user_id=U1)
    with pytest.raises(QuantityOutOfBounds):
        cart.add(U2, 0, max_distinct_items=5, max_quantity=10)
    assert cart.is_empty


def test_add_quantity_above_max_rejected():
    cart = Cart(user_id=U1)
    with pytest.raises(QuantityOutOfBounds):
        cart.add(U2, 11, max_distinct_items=5, max_quantity=10)
    assert cart.is_empty


def test_add_duplicate_exceeding_max_quantity_rejected_without_partial_state():
    cart = Cart(user_id=U1)
    cart.add(U2, 6, max_distinct_items=5, max_quantity=10)
    with pytest.raises(QuantityOutOfBounds):
        cart.add(U2, 5, max_distinct_items=5, max_quantity=10)
    assert cart.items[U2].quantity == 6


def test_add_beyond_max_distinct_items_rejected_cart_unchanged():
    cart = Cart(user_id=U1)
    for i in range(3):
        cart.add(uuid.UUID(int=i), 1, max_distinct_items=3, max_quantity=10)
    with pytest.raises(CartLimitExceeded):
        cart.add(U2, 1, max_distinct_items=3, max_quantity=10)

    assert len(cart.items) == 3
    assert U2 not in cart.items


def test_set_quantity():
    cart = Cart(user_id=U1)
    cart.add(U2, 1, max_distinct_items=5, max_quantity=10, added_at=NOW)
    cart.set_quantity(U2, 7, max_quantity=10)

    assert cart.items[U2].quantity == 7
    assert cart.items[U2].added_at == NOW


def test_set_quantity_bounds_rejected():
    cart = Cart(user_id=U1)
    cart.add(U2, 1, max_distinct_items=5, max_quantity=10)
    for bad in (0, -1, 11):
        with pytest.raises(QuantityOutOfBounds):
            cart.set_quantity(U2, bad, max_quantity=10)
    assert cart.items[U2].quantity == 1


def test_set_quantity_missing_item():
    cart = Cart(user_id=U1)
    with pytest.raises(KeyError):
        cart.set_quantity(U2, 1, max_quantity=10)


def test_remove_missing_item_raises():
    cart = Cart(user_id=U1)
    with pytest.raises(KeyError):
        cart.remove(U2)


def test_remove_and_clear():
    cart = Cart(user_id=U1)
    cart.add(U2, 1, max_distinct_items=5, max_quantity=10)
    cart.add(U1, 2, max_distinct_items=5, max_quantity=10)
    cart.remove(U2)
    assert U2 not in cart.items
    cart.clear()
    assert cart.is_empty


def test_check_quantity_bounds():
    assert check_quantity(1, 100) is None
    assert check_quantity(100, 100) is None
    for bad in (0, -1, 101):
        with pytest.raises(QuantityOutOfBounds):
            check_quantity(bad, 100)


def test_cart_item_rejects_zero_quantity():
    with pytest.raises(QuantityOutOfBounds):
        CartItem(product_id=U1, quantity=0, added_at=NOW)
