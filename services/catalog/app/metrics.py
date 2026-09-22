"""Prometheus-счётчики, специфичные для каталога.

Общие (request'ы, latency, request_id) предоставляет
``common.middleware.PrometheusMetricsMiddleware``; здесь — только счётчики
синхронизации и поиска. Регистрация в ``prometheus_client`` глобальная,
поэтому коллизий между сервисами в одном процессе не бывает.
"""

from prometheus_client import Counter

#: Неудачные операции релея синхронизации PG -> ES (наблюдаемость отказов).
catalog_sync_failures_total = Counter(
    "catalog_sync_failures_total",
    "Total number of failed outbox relay operations",
    ["operation"],
)

#: Ошибки записи/удаления документов при индексации/реиндексе.
catalog_index_errors_total = Counter(
    "catalog_index_errors_total",
    "Total number of ES index operation errors",
)

#: Поиск вернул 503 (breaker открыт / ES недоступен).
catalog_search_unavailable_total = Counter(
    "catalog_search_unavailable_total",
    "Total number of searches failed with SEARCH_UNAVAILABLE",
)
