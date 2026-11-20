"""Unit-тесты stateless-проверки пересечения порога low-stock (D8)."""

from __future__ import annotations

import pytest

from app.services.events import is_low_stock_crossing


def test_crossing_detected() -> None:
    assert is_low_stock_crossing(
        available_before=15, available_after=9, threshold=10
    )


def test_exactly_to_threshold_is_not_crossing() -> None:
    # available_after == threshold: порог не пересечён (порог включительно).
    assert not is_low_stock_crossing(
        available_before=15, available_after=10, threshold=10
    )


def test_no_crossing_above_threshold() -> None:
    assert not is_low_stock_crossing(
        available_before=50, available_after=40, threshold=10
    )


def test_no_crossing_below_threshold() -> None:
    # Уже ниже порога — повторные уменьшения не переэмитят alert.
    assert not is_low_stock_crossing(
        available_before=8, available_after=3, threshold=10
    )


def test_threshold_zero_disabled() -> None:
    assert not is_low_stock_crossing(
        available_before=5, available_after=0, threshold=0
    )


def test_negative_threshold_disabled() -> None:
    assert not is_low_stock_crossing(
        available_before=5, available_after=0, threshold=-1
    )


def test_rearm_is_implicit() -> None:
    # Поднятие выше порога (restock) не хранит флага: новое пересечение
    # детектируется снова stateless-проверкой.
    assert not is_low_stock_crossing(
        available_before=9, available_after=20, threshold=10
    )
    assert is_low_stock_crossing(
        available_before=20, available_after=5, threshold=10
    )


@pytest.mark.parametrize(
    "before,after,threshold,expected",
    [
        (15, 9, 10, True),
        (10, 9, 10, True),
        (15, 10, 10, False),
        (9, 5, 10, False),
        (0, 0, 10, False),
        (10, 0, 10, True),
    ],
)
def test_matrix(before: int, after: int, threshold: int, expected: bool) -> None:
    assert (
        is_low_stock_crossing(
            available_before=before, available_after=after, threshold=threshold
        )
        is expected
    )
