"""Unit-тесты circuit breaker релея (открытие/полуоткрытие/закрытие)."""

from __future__ import annotations

import pytest

from app.services.breaker import BreakerOpenError, CircuitBreaker


async def _ok() -> str:
    return "ok"


async def _fail() -> str:
    raise RuntimeError("boom")


async def test_stays_closed_on_success() -> None:
    breaker = CircuitBreaker(failure_threshold=3, open_seconds=60.0)
    assert await breaker.call(_ok) == "ok"
    assert breaker.state == "closed"


async def test_opens_after_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=2, open_seconds=60.0)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(_fail)
    assert breaker.state == "open"
    with pytest.raises(BreakerOpenError):
        await breaker.call(_ok)


async def test_half_open_then_close() -> None:
    breaker = CircuitBreaker(failure_threshold=1, open_seconds=0.0)
    with pytest.raises(RuntimeError):
        await breaker.call(_fail)
    assert breaker.state == "open"
    # open_seconds == 0 -> сразу разрешается проверочная попытка.
    assert await breaker.call(_ok) == "ok"
    assert breaker.state == "closed"


async def test_half_open_fail_reopens() -> None:
    breaker = CircuitBreaker(failure_threshold=1, open_seconds=0.0)
    with pytest.raises(RuntimeError):
        await breaker.call(_fail)
    with pytest.raises(RuntimeError):
        await breaker.call(_fail)
    assert breaker.state == "open"
