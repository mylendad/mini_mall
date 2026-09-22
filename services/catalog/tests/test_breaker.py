"""Юнит-тесты circuit breaker (8.1) на моках и времени."""

import pytest

from app.services.breaker import BreakerOpenError, CircuitBreaker


class _Failing:
    def __init__(self):
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        raise ConnectionError("es down")


class _Ok:
    def __init__(self):
        self.calls = 0

    async def __call__(self, value: int = 0) -> int:
        self.calls += 1
        return value


async def _runner(fn):
    return await fn()


async def test_breaker_stays_closed_on_success():
    breaker = CircuitBreaker(failure_threshold=3, open_seconds=30.0)
    ok = _Ok()
    for _ in range(5):
        assert await breaker.call(_runner, ok) == 0
    assert breaker.state == "closed"
    assert breaker.consecutive_failures == 0


async def test_breaker_trips_open_after_threshold():
    breaker = CircuitBreaker(failure_threshold=3, open_seconds=30.0)
    failing = _Failing()
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await breaker.call(_runner, failing)
    assert breaker.state == "open"

    with pytest.raises(BreakerOpenError):
        await breaker.call(_runner, failing)
    assert failing.calls == 3  # новых вызовов к ES не было


async def test_breaker_moves_from_open_to_half_open_and_recovers():
    breaker = CircuitBreaker(failure_threshold=2, open_seconds=0.0)
    failing = _Failing()
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await breaker.call(_runner, failing)
    assert breaker.state == "open"

    # open_seconds истекло -> одна пробная попытка в half_open
    ok = _Ok()
    assert await breaker.call(_runner, ok) == 0
    assert breaker.state == "closed"
    assert breaker.consecutive_failures == 0


async def test_breaker_half_open_failure_reopens():
    breaker = CircuitBreaker(failure_threshold=2, open_seconds=0.0)
    failing = _Failing()
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await breaker.call(_runner, failing)
    assert breaker.state == "open"

    with pytest.raises(ConnectionError):
        await breaker.call(_runner, failing)
    assert breaker.state == "open"


async def test_breaker_state_changed_callback():
    transitions: list[str] = []
    breaker = CircuitBreaker(
        failure_threshold=1, open_seconds=30.0, state_changed=transitions.append
    )
    failing = _Failing()
    with pytest.raises(ConnectionError):
        await breaker.call(_runner, failing)
    assert transitions == ["open"]
