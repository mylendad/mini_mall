# Сервис каталога (`services/catalog`)

Автономный микросервис каталога товаров: CRUD категорий и продуктов, полнотекстовый
поиск через Elasticsearch (производная проекция), фоновая синхронизация PG → ES
через outbox-паттерн, circuit breaker и метрики Prometheus.

База данных PostgreSQL (`mini_mall_catalog`) — единственный источник истины;
Elasticsearch используется **только** для поисковых запросов и может быть
пересоздан из БД через admin-reindex.

## Структура

```text
services/catalog/
├── pyproject.toml          # зависимости, pytest-asyncio (auto), per-file B008
├── Dockerfile              # multi-stage из корня репо
├── alembic.ini             # prepend_sys_path = .
├── alembic/
│   ├── env.py              # async-движок, URL из settings.database_url
│   └── versions/
│       └── 0001_initial.py  # categories + products + index_outbox
├── app/
│   ├── main.py             # create_app, lifespan (tracing, Redis, relay start/stop), handlers
│   ├── config.py           # Settings(BaseAppSettings): DB, ES, Redis, OTel, outbox/relay tuning
│   ├── database.py         # async engine, async_session_maker, Base, get_db
│   ├── elasticsearch.py    # AsyncElasticsearch, CATALOG_INDEX, ensure/delete index
│   ├── cache.py            # Redis read-through кэш продуктов (D11), graceful degradation
│   ├── metrics.py          # prometheus counters (sync/search failures)
│   ├── errors.py           # IntegrityErrorMapper (PG → HTTP codes), error_detail
│   ├── api/
│   │   ├── categories.py   # CRUD /api/v1/categories
│   │   ├── products.py     # CRUD /api/v1/products (router includes BEFORE {id})
│   │   ├── search.py       # GET /api/v1/products/search (requires ES)
│   │   └── admin.py        # POST /api/v1/admin/reindex
│   ├── schemas/
│   │   └── catalog.py      # Pydantic-схемы (ProductResponse.price: str, validator)
│   ├── models/
│   │   ├── catalog.py      # Category (passive_deletes), Product (CHECK price>0)
│   │   └── outbox.py       # IndexOutbox: envelope JSONB, status, attempt_count
│   ├── repositories/
│   │   ├── category_repo.py
│   │   └── product_repo.py  # server-side filtering/sort/paging
│   └── services/
│       ├── categories.py   # business logic (CATEGORY_HAS_PRODUCTS restriction)
│       ├── products.py     # commit PG, then trigger outbox sync
│       ├── indexer.py       # product_document, index/delete product, reindex_all
│       ├── relay.py        # process_outbox + outbox retention, relay_job (lifespan asyncio.Task)
│       ├── breaker.py      # BreakerOpenError, CircuitBreaker, search_breaker + relay_breaker
│       └── search.py       # build_query (ES DSL), search_products → ProductSearchResult
└── tests/
    ├── conftest.py            # Testcontainers PG 16 + ES 8.12, Alembic, fixtures
    ├── test_schemas.py        # 45 unit tests (schemas, errors, indexer, breaker, params)
    ├── test_catalog_postgres.py  # 27 PG integration tests (categories, products, outbox)
    └── test_search_elasticsearch.py  # 14 ES tests (mapping, relay→search, admin, 503)
```

## Конфигурация

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/mini_mall_catalog` | Асинхронный URL PostgreSQL |
| `ELASTICSEARCH_URL` | `http://localhost:9200` | Базовый URL Elasticsearch |
| `ES_INDEX_PREFIX` | `catalog_products` | Префикс имени индекса (`_v1`) |
| `ES_REQUEST_TIMEOUT` | `5.0` | Таймаут HTTP-запроса к ES (сек) |
| `ES_CONNECT_TIMEOUT` | `5.0` | Таймаут ES-соединения (сек) |
| `OUTBOX_POLL_INTERVAL` | `1.0` | Интервал сканирования outbox (сек) |
| `OUTBOX_MAX_ATTEMPTS` | `10` | Макс. число попыток перед пропуском |
| `OUTBOX_BACKOFF_BASE` | `1.0` | База экспоненциальной задержки (сек) |
| `OUTBOX_RETENTION_SECONDS` | `86400` | Срок жизни обработанных строк outbox; `0` — без чистки |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis read-through кэш `GET /products/{id}` |
| `CACHE_TTL_SECONDS` | `300` | TTL кэш-ключа продукта (сек) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *(пусто)* | OTLP/HTTP endpoint трейсов (Jaeger); пусто — tracing выключен |

## База данных

### `categories`

| Поле | Тип | Свойства |
|---|---|---|
| `id` | UUID | PK, `uuid.uuid4` |
| `name` | VARCHAR(255) | UNIQUE, trimmed |
| `created_at` / `updated_at` | TIMESTAMP(tz) | UTC, автозаполнение |

### `products`

| Поле | Тип | Свойства |
|---|---|---|
| `id` | UUID | PK |
| `category_id` | UUID | FK → `categories.id` ON DELETE RESTRICT |
| `sku` | VARCHAR(64) | UNIQUE, pattern `[A-Z0-9-]{1,64}` |
| `name` | VARCHAR(255) | NOT NULL |
| `description` | TEXT | nullable |
| `price` | NUMERIC(12,2) | CHECK `price > 0` |
| `currency` | CHAR(3) | regex `[A-Z]{3}` (ISO-4217) |
| `attributes` | JSONB | nullable, `flattened` в ES |
| `is_active` | BOOLEAN | default true |
| `created_at` / `updated_at` | TIMESTAMP(tz) | UTC |

### `index_outbox`

| Поле | Тип | Свойства |
|---|---|---|
| `id` | BIGSERIAL | PK |
| `event_id` | UUID | UNIQUE |
| `envelope` | JSONB | `{"event_type", "event_version", "payload": {полный снимок продукта}}` |
| `status` | VARCHAR(32) | `pending` → `processed` |
| `attempt_count` | INTEGER | начальное 0 |
| `last_error` | TEXT | nullable, до 500 символов |
| `created_at` / `processed_at` | TIMESTAMP(tz) | |

### Миграции

```bash
cd services/catalog
DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/mini_mall_catalog" \
  ../.venv/bin/alembic upgrade head
```

## Elasticsearch

### Индекс

Имя: `catalog_products_v1` (формируется `{ES_INDEX_PREFIX}_v1`).

Mapping (D5):

| Поле | Тип | Комментарий |
|---|---|---|
| `id`, `sku`, `category_id` | `keyword` | точные фильтры |
| `name` | `text` + `keyword` | полнотекст + сортировка |
| `description` | `text` | полнотекст |
| `price` | `scaled_float` (factor=100) | диапазонные фильтры |
| `currency` | `keyword` | |
| `attributes` | `flattened` | произвольные JSON |
| `is_active` | `boolean` | |
| `created_at`, `updated_at` | `date` | |

### Синхронизация PG → ES (outbox-паттерн)

1. При `CREATE/UPDATE/DELETE` продукта в PG коммитится запись `index_outbox`
   (в той же транзакции, в `services/products.py`). Подпись события — публичное
   доменное событие с **толстым payload** (Event-Carried State Transfer):
   `payload` содержит полный снимок продукта (`ProductResponse`), а не
   внутреннюю команду. Это делает события пригодными для будущего
   Kafka-паблишера и внешних потребителей (Analytics, Cart) без изменения
   bounded-контекста каталога.
2. Фоновая asyncio-задача `relay_job` раз в `OUTBOX_POLL_INTERVAL` секунд
   сканирует `pending`-строки и для каждой:
   - Игнорирует состояние толстого payload и использует только `id` из него:
     перечитывает актуальный продукт из PG (авторитетное состояние).
   - Применяет операцию `index_product` / `delete_product` через circuit breaker.
   - Помечает `processed` + `processed_at`.
3. Строки с `attempt_count >= OUTBOX_MAX_ATTEMPTS` пропускаются (не удаляются —
   остаются как наблюдаемый pending).

**Гарантии консистентности**: ES — производная проекция. Между записью в PG
и индексацией ES допускается задержка (порядка `OUTBOX_POLL_INTERVAL` секунд).
Для мгновенной видимости используйте `POST /admin/reindex`.

### Redis-кэш точечных чтений (D11)

`GET /api/v1/products/{id}` читается через read-through кэш
(`catalog:product:{id}`, TTL `CACHE_TTL_SECONDS`):

- Промах → чтение из PostgreSQL → запись в кэш.
- Попадание → ответ из кэша без обращения к БД.
- При `PATCH`/`DELETE` продукта ключ активно удаляется после commit в PG
  (минимизация устаревших данных).
- Любой сбой Redis (`RedisError`/`OSError`) логируется, путь чтения деградирует
  на PostgreSQL и продолжает выдавать 200 (требование спеки).

### OpenTelemetry (трейсинг)

Если задан `OTEL_EXPORTER_OTLP_ENDPOINT`, в `lifespan` инициализируются
`FastAPIInstrumentor` (входящие HTTP-запросы, W3C `traceparent` извлекается
глобальным пропагатором) и `SQLAlchemyInstrumentor` (span'ы запросов к БД).
Exporter — OTLP/HTTP (5s timeout, `BatchSpanProcessor`). Без эндпоинта трейсинг
выключен и не создаёт накладных расходов. `request_id`/`correlation_id`
по-прежнему проставляются `RequestIDMiddleware`.

### Circuit Breaker

Синглтон `catalog_breaker` в `services/breaker.py`:
- `failure_threshold=5` → OPEN.
- OPEN: `catalog_search_unavailable_total` инкрементируется, возвращается `503 SEARCH_UNAVAILABLE`.
- Через `open_seconds=30` → HALF-OPEN, следующий запрос пробной.
- Успешный → CLOSED; провал → обратно OPEN.

### Полное переиндексирование

`POST /api/v1/admin/reindex` (без authorisation-заголовков — открыто; с
`X-User-Roles` без `admin` → `403`): удаляет индекс, пересоздаёт, пакетно
сканирует все продукты из PG и bulk-индексирует.

## API

### Categories (`/api/v1/categories`)

| Метод | Описание |
|---|---|
| `POST /categories` | Создать; 201, 409 DUPLICATE_CATEGORY, 422 VALIDATION_ERROR |
| `GET /categories` | Список (created_at ASC) |
| `GET /categories/{id}` | Одна категория; 404 CATEGORY_NOT_FOUND |
| `PATCH /categories/{id}` | Обновить имя; 409 DUPLICATE_CATEGORY, 404 |
| `DELETE /categories/{id}` | 204; 404, 409 CATEGORY_HAS_PRODUCTS (FK RESTRICT) |

### Products (`/api/v1/products`)

| Метод | Описание |
|---|---|
| `POST /products` | Создать; 201, 409 DUPLICATE_SKU, 422 INVALID_CATEGORY |
| `GET /products` | Список: `?category_id=`, `?is_active=`, `?sort=`, `?order=`, `?offset=`, `?limit=` |
| `GET /products/search` | **Регистрируется ДО** `/products/{id}`; см. Search |
| `GET /products/{id}` | Одна карточка; 404 PRODUCT_NOT_FOUND; read-through кэш Redis |
| `PATCH /products/{id}` | Обновить; 404/409/422 |
| `DELETE /products/{id}` | 204; 404 |

**Сортировка `GET /products`**: `created_at` (default), `updated_at`, `name`, `price`.

### Search (`GET /api/v1/products/search`)

Параметры: `q` (полный текст по name/description), `category_id`, `min_price`,
`max_price`, `sort` (`relevance`/`price`/`created_at`/`name`), `order`
(`asc`/`desc`), `offset`, `limit`.

- Пустой/пробельный `q` → match_all, только `is_active=true`.
- Breaker OPEN → **503 SEARCH_UNAVAILABLE**.
- ES недоступен → 503.
- Фасеты: ответ всегда включает `facets` — агрегации по отфильтрованному
  набору (`by_category` — counts по категориям, `price_ranges` — распределение
  по ценовым корзинам). Derived из результатов поиска, не утечка DSL.

Ответ:

```json
{
  "items": [{"id", "sku", "name", "description", "price", "currency",
             "category_id", "category_name", "is_active", "created_at", "updated_at"}],
  "total": 12,
  "offset": 0,
  "limit": 20,
  "facets": {
    "by_category": [{"key": "<uuid>", "count": 7}, "..."],
    "price_ranges": [{"key": "*-25.0", "count": 3}, "..."]
  }
}
```

**Важно**: `price` в ответе — `str` (из `ProductSearchResult.price: str`), в
отличие от `ProductResponse.price: str` (Decimal→str через validator). Если
ES-клиент вернул `float`, значение может быть `"10.0"` вместо `"10.00"`.

### Admin (`POST /api/v1/admin/reindex`)

| Заголовок | Поведение |
|---|---|
| без `X-User-Roles` | 200 (открытый доступ) |
| `X-User-Roles: catalog:read` | 403 FORBIDDEN |
| `X-User-Roles: admin, crm` | 200, полное переиндексирование |

Ответ: `{"index": "catalog_products_v1", "reindexed": N}`.

### Health и метрики

- `GET /health/live` → `{"status": "alive"}`
- `GET /health/ready` → `{"status": "ready"}` (SELECT 1) / `503 unhealthy`
- `GET /metrics` → Prometheus counters:
  - `catalog_sync_failures_total{operation="product.created|updated|deleted"}`
  - `catalog_index_errors_total`
  - `catalog_search_unavailable_total` (инкрементируется при breaker OPEN)

### Формат ошибок

Единый `ErrorResponse`:

```json
{
  "error": {"code": "DUPLICATE_SKU", "message": "Product with SKU ... already exists", "details": null},
  "request_id": "req-..."
}
```

| Код | HTTP | Описание |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Pydantic-ошибки |
| `CATEGORY_NOT_FOUND` | 404 | Категория не найдена |
| `PRODUCT_NOT_FOUND` | 404 | Продукт не найден |
| `DUPLICATE_CATEGORY` | 409 | Имя категории занято |
| `DUPLICATE_SKU` | 409 | SKU дублируется |
| `CATEGORY_HAS_PRODUCTS` | 409 | Нельзя удалить категорию с продуктами |
| `INVALID_CATEGORY` | 422 | category_id не существует |
| `INVALID_SORT` | 422 | Поле сортировки не в whitelist |
| `SEARCH_UNAVAILABLE` | 503 | Breaker OPEN или ES недоступен |
| `INTERNAL_ERROR` | 500 | Необработанное исключение |

## Тестирование

```bash
cd services/catalog
../.venv/bin/pytest tests/ -q     # все 86 тестов
```

### Юнит-тесты (45)

`test_schemas.py`, `test_errors.py`, `test_search_params.py`, `test_indexer.py`,
`test_breaker.py` — проверки валидации, маппинга ошибок, построения ES-query,
построения документа и circuit breaker.

### PostgreSQL интеграционные (27)

`test_catalog_postgres.py` — Testcontainers `postgres:16-alpine`, реальные
миграции Alembic: CRUD, unique/FK ограничения, пагинация/сортировка,
outbox-commit (3 события, rollback не оставляет строк).

### Elasticsearch интеграционные (14)

`test_search_elasticsearch.py` — Testcontainers `elasticsearch:8.12.2` (с
пониженными disk watermarks для CI): mapping, relay→search (полный текст,
фильтры, сортировка, пагинация), update/delete отражаются, admin-reindex
(открытый/403/authorized), 503 SEARCH_UNAVAILABLE при мёртвом порте.

**Примечание**: ES-тесты требуют ~70с на cold start (контейнер + JVM + индексы).
На хосте с занятым диском (>90%) ES-шарды могут не аллоцироваться —
фикстура снижает watermarks до 95%/98% через env контейнера.

Pytest настроен в `pyproject.toml`: `asyncio_mode = "auto"`.

## Контейнеризация и запуск

```bash
# локально:
cd services/catalog && ../.venv/bin/uvicorn app.main:app --reload --port 8000

# Docker (из корня репозитория):
docker build -f services/catalog/Dockerfile -t catalog-service .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://... \
  -e ELASTICSEARCH_URL=http://localhost:9200 \
  catalog-service

# автономное создание индекса:
docker run catalog-service python -m app.elasticsearch
```

## Связанные документы

- OpenSpec `catalog-service`: `openspec/changes/catalog-service/`
- Общая библиотека: [libs-common.md](../libs-common.md)
- Архитектура: [architecture.md](../architecture.md)
