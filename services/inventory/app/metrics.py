"""Prometheus-счётчики, специфичные для инвентаря.

Общие (request'ы, latency, request_id) предоставляет
``common.middleware.PrometheusMetricsMiddleware``; здесь — только счётчики
резервов, релея outbox и задания истечения. Регистрация в
``prometheus_client`` глобальная, поэтому коллизий между сервисами в одном
процессе не бывает.
"""

from prometheus_client import Counter, Gauge

#: Резервы по исходу операции (``reserved``/``insufficient``/``confirmed``/
#: ``released``/``expired``).
reservations_total = Counter(
    "inventory_reservations_total",
    "Total number of reservation operations by outcome",
    ["outcome"],
)

#: Строки outbox в состоянии ``pending`` (наблюдение за отставанием релея).
outbox_pending = Gauge(
    "inventory_outbox_pending",
    "Number of pending outbox rows",
)

#: Строки outbox, исчерпавшие попытки публикации.
outbox_failures_total = Counter(
    "inventory_outbox_failures_total",
    "Total number of outbox rows that exhausted their publish attempts",
)

#: Проходы задания истечения резервов и обработанные им строки.
expiration_runs_total = Counter(
    "inventory_expiration_runs_total",
    "Total number of expiration job runs",
)

#: Резервы, переведённые в ``expired`` заданием истечения.
expiration_processed_total = Counter(
    "inventory_expiration_processed_total",
    "Total number of reservations expired by the expiration job",
)
