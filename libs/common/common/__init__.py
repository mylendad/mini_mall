"""Общая библиотека ``common``.

Строго инфраструктурные компоненты для микросервисов платформы:
конфигурация, логирование, middleware трассировки, Prometheus-метрики,
стандартный формат ошибок и конверт событий.

Сервисы подключают ``common`` как обычную установленную зависимость и не
должны размещать здесь доменную логику (см. спецификацию foundation).
"""
from common.config import BaseAppSettings
from common.errors import ErrorDetail, ErrorResponse
from common.events import EventEnvelope
from common.logging import setup_logging
from common.middleware import RequestIDMiddleware
from common.observability import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    PrometheusMetricsMiddleware,
)

__all__ = [
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "BaseAppSettings",
    "ErrorDetail",
    "ErrorResponse",
    "EventEnvelope",
    "PrometheusMetricsMiddleware",
    "RequestIDMiddleware",
    "setup_logging",
]