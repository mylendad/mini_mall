"""Наблюдаемость: Prometheus-метрики HTTP-запросов.

Предоставляет счётчик запросов и гистограмму задержек, а также middleware
для автоматического сбора этих метрик со всех маршрутов приложения.
"""
import time

from fastapi import Request, Response
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"]
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"]
)

class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Считает количество запросов и их задержку.

    Метки: ``method``, ``endpoint`` и (для счётчика) ``status_code``.
    Добавьте в приложение как обычный middleware; метрики отдаются через
    ``/metrics`` (см. :func:`common.observability` и шаблон сервиса).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Замеряет время обработки запроса и обновляет метрики.

        Параметры:
            request: Входящий HTTP-запрос.
            call_next: Следующий обработчик в цепочке middleware.

        Возвращает:
            HTTP-ответ (метрики обновляются до возврата).
        """
        method = request.method
        path = request.url.path
        start_time = time.time()

        response = await call_next(request)

        duration = time.time() - start_time
        status_code = str(response.status_code)

        REQUEST_COUNT.labels(method=method, endpoint=path, status_code=status_code).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=path).observe(duration)

        return response
