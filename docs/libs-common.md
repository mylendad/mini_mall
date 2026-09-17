# Общая библиотека `common` (`libs/common`)

`libs/common` — единственная общая библиотека платформы. Её назначение — **только
инфраструктура**: то, что одинаково для всех сервисов и не содержит доменной
логики. Каждый сервис подключает её как обычную установленную зависимость и в
контейнере «не замечает» остального репозитория.

## Структура

```text
libs/common/
├── pyproject.toml        # пакет: имя, версия 0.1.0, зависимости
└── common/               # импортируемая часть
    ├── __init__.py       # публичное API (см. ниже)
    ├── config.py         # BaseAppSettings
    ├── errors.py         # ErrorDetail, ErrorResponse
    ├── events.py         # EventEnvelope
    ├── logging.py        # setup_logging
    ├── middleware.py     # RequestIDMiddleware
    └── observability.py  # PrometheusMetricsMiddleware + метрики
```

## Публичное API

Подключив `common`, сервис получает:

| Символ | Назначение |
| --- | --- |
| `BaseAppSettings` | Базовый класс настроек (чтение env + `.env`, `extra="ignore"`). Сервис наследует и переопределяет свои поля |
| `ErrorDetail`, `ErrorResponse` | Единый формат ответа об ошибке: `{"error": {"code", "message", "details"}, "request_id"}` |
| `EventEnvelope` | Конверт событий для Kafka: `event_id`, `event_type`, `event_version`, `occurred_at`, `producer`, `correlation_id`, `payload` |
| `setup_logging(log_level)` | Настройка structlog → JSON-строки в stdout с уровнем и timestamp |
| `RequestIDMiddleware` | Пробрасывает/генерирует `X-Request-ID` и `X-Correlation-ID`, кладёт в контекст structlog |
| `PrometheusMetricsMiddleware` | `http_requests_total` и `http_request_duration_seconds` с метками method/endpoint/status_code |

## Пример использования в сервисе

```python
from common.config import BaseAppSettings

class Settings(BaseAppSettings):
    app_name = "auth-service"
    database_url = "postgresql+asyncpg://..."
    jwt_secret = "..."
```

```python
app.add_middleware(RequestIDMiddleware)
app.add_middleware(PrometheusMetricsMiddleware)
setup_logging(settings.log_level)
```

## Как добавлять новый общий код

1. Всё, что попадает в `libs/common`, обязано быть **инфраструктурой** (см.
   границы в [architecture.md](architecture.md)). Доменная логика — наружу.
2. Добавьте файл в `libs/common/common/` и, при необходимости, экспортируйте
   символ в `__init__.py`.
3. Обновите `dependencies` в `libs/common/pyproject.toml`, если добавили новую
   зависимость.
4. Напишите тест. Юнит-тесты инфраструктуры — в корневых `tests/` или в
   каталоге пакета.
5. Не забывайте docstrings (по ним генерируется документация).

## Правила для зависимостей

Пакет `common` **не зависят** от сервисного кода. Его собственные зависимости:

- `fastapi`, `starlette` — middleware;
- `pydantic`, `pydantic-settings` — модели и настройки;
- `structlog` — логирование;
- `prometheus-client` — метрики.

## Подключение к сервису

### pyproject.toml сервиса

```toml
[project]
dependencies = [
    "common>=0.1.0",
    ...
]

[tool.uv.sources]
common = { path = "../../libs/common", editable = true }
```

### Локальная установка

```bash
.venv/bin/pip install -e libs/common
```

или для uv: `uv sync` (путь к `common` resolve из секции `[tool.uv.sources]`).

### Docker

См. [Контейнеризация](docker.md) — первый этап сборки делает wheel для
`common`, второй — для сервиса; в образе `common` уже установлена как обычная
библиотека.

## Ограничения и известные предостережения

- Пакет `common` **не** должен импортировать `app.*` или другие сервисы —
  иначе нарушается автономность.
- Relative file-URL на уровне pip чувствителен к текущему каталогу: при
  ручной установке запускайте команду из каталога, где расположен
  `pyproject.toml` сервиса (либо используйте uv с `[tool.uv.sources]`).
- Смотрите также спецификацию foundation: `openspec/specs/foundation/spec.md`.