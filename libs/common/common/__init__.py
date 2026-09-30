"""Общая библиотека ``common``.

Строго инфраструктурные компоненты для микросервисов платформы:
конфигурация, логирование, middleware трассировки, Prometheus-метрики,
стандартный формат ошибок и конверт событий.

Сервисы подключают ``common`` как обычную установленную зависимость и не
должны размещать здесь доменную логику (см. спецификацию foundation).
"""

from common.config import BaseAppSettings
from common.errors import (
    HTTP_ERROR,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    error_detail,
)
from common.events import EventEnvelope
from common.logging import setup_logging
from common.middleware import RequestIDMiddleware
from common.observability import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    PrometheusMetricsMiddleware,
)

__all__ = [
    "HTTP_ERROR",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "BaseAppSettings",
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "EventEnvelope",
    "PrometheusMetricsMiddleware",
    "RequestIDMiddleware",
    "error_detail",
    "setup_logging",
]
