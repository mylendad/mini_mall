"""Настройка структурированного JSON-логирования на базе structlog."""
import logging
import sys

import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """Настраивает базовое логирование и structlog для JSON-вывода в stdout.

    Формат вывода: JSON-строки с полями ``event``, ``level``, ``timestamp``.
    Вызов идемпотентный; определён в начале жизненного цикла приложения.

    Параметры:
        log_level: Уровень логирования (например, ``"INFO"``).
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
