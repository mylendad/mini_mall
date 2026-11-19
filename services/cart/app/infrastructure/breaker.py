"""Circuit breaker для вызовов Catalog (порт из services/catalog, задача 3.2).

Состояния: ``closed`` -> ``open`` -> ``half_open`` -> ``closed``. Размыкание
после ``failure_threshold`` подряд ошибок; после ``open_seconds`` одна
проверочная попытка проходит в ``half_open``: успех возвращает цепь в
``closed``, ошибка — снова в ``open``. Параметры берутся из настроек.
Модуль не зависит от httpx, поэтому тестируется с моками.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.config import settings

T = TypeVar("T")


class BreakerOpenError(Exception):
    """Catalog временно недоступен: circuit breaker открыт (-> 503)."""


class CircuitBreaker:
    """Пороговый breaker на подряд идущих ошибках с half-open проверкой."""

    def __init__(
        self,
        failure_threshold: int = 5,
        open_seconds: float = 30.0,
        state_changed: Callable[[str], None] | None = None,
    ):
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self.state_changed = state_changed
        self._consecutive_failures = 0
        self._state = "closed"
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        """Текущее состояние breaker (``closed``/``open``/``half_open``)."""
        return self._state

    @property
    def consecutive_failures(self) -> int:
        """Число подряд идущих ошибок (для отладки и тестов)."""
        return self._consecutive_failures

    def _set_state(self, new: str) -> None:
        if new != self._state:
            self._state = new
            if self.state_changed is not None:
                self.state_changed(new)

    def _open(self) -> None:
        self._opened_at = time.monotonic()
        self._set_state("open")

    def reset(self) -> None:
        """Возвращает цепь в ``closed`` (используется в тестах)."""
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._set_state("closed")

    async def call(
        self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
    ) -> T:
        """Выполняет ``fn(*args, **kwargs)`` под защитой breaker.

        Исключения:
            BreakerOpenError: цепь открыта и время ``open_seconds`` не вышло.
            оригинальное исключение от ``fn``: при регистрации ошибки breaker.
        """
        if self._state == "open":
            if time.monotonic() - self._opened_at >= self.open_seconds:
                self._set_state("half_open")
            else:
                raise BreakerOpenError("circuit breaker is open")
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._open()
            raise
        self._consecutive_failures = 0
        if self._state == "half_open":
            self._set_state("closed")
        return result


#: Breaker HTTP-вызовов Catalog (валидация продукта при добавлении в корзину).
catalog_breaker = CircuitBreaker(
    failure_threshold=settings.breaker_failure_threshold,
    open_seconds=settings.breaker_open_seconds,
)
