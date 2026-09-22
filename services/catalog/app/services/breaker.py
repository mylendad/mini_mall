"""Лёгкий circuit breaker поверх взаимодействий с Elasticsearch.

Состояния: ``closed`` -> ``open`` -> ``half_open`` -> ``closed``. Размыкание
происходит после ``failure_threshold`` подряд идущих ошибок; после
``open_seconds`` одно проверочное взаимодействие пропускается в
``half_open``: успех возвращает breaker в ``closed``, ошибка — снова в
``open``. Управляется :class:`~app.app.elasticsearch.es_client`, но сам не
зависит от драйвера ES, поэтому легко тестируется с моком.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.config import settings

T = TypeVar("T")


class BreakerOpenError(Exception):
    """Es временно недоступен: circuit breaker открыт (503 ``SEARCH_UNAVAILABLE``)."""


class CircuitBreaker:
    """Пороговый breaker на подряд идущих ошибках с half-open проверкой.

    Параметры:
        failure_threshold: Сколько подряд ошибок нужно, чтобы разомкнуть цепь.
        open_seconds: При каком простое разрешить одну проверочную попытку.
        state: Текущее состояние (``closed``/``open``/``half_open``).
        state_changed: Метод обратного вызова при смене состояния (для метрик).
    """

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


#: Breaker поиска (пользовательские запросы и admin-reindex). Изолирован от
#: релея: таймауты поиска не останавливают индексацию outbox и наоборот.
search_breaker = CircuitBreaker(
    failure_threshold=settings.breaker_failure_threshold,
    open_seconds=settings.breaker_open_seconds,
)

#: Breaker фонового релея outbox PG -> ES.
relay_breaker = CircuitBreaker(
    failure_threshold=settings.breaker_failure_threshold,
    open_seconds=settings.breaker_open_seconds,
)
