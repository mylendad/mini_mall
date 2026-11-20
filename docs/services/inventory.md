# Сервис инвентаря (`services/inventory`)

Автономный микросервис складского учёта: учёт остатков по SKU, API доступности,
резервы с защитой от перепродажи (атомарные условные UPDATE), жизненный цикл
резервов (confirm / release / автоистечение), контракт участника Saga checkout,
публикация событий через outbox-паттерн в Kafka и low-stock оповещения.

База данных PostgreSQL (`mini_mall_inventory`) — единственный источник истины;
Kafka — единственный канал межсервисной интеграции. Redis и Elasticsearch не
используются.

## Структура

```text
services/inventory/
├── pyproject.toml              # зависимости, pytest-asyncio (auto), per-file B008
├── Dockerfile                  # multi-stage из корня репо
├── .env.example                # документация переменных окружения
├── alembic.ini                 # prepend_sys_path = .
├── alembic/
│   ├── env.py                  # async-движок, URL из settings.database_url
│   └── versions/
│       ├── 0001_stock_items.py        # stock_items
│       ├── 0002_reservations.py       # reservations
│       ├── 0003_processed_commands.py # processed_commands
│       └── 0004_inventory_outbox.py   # inventory_outbox
├── app/
│   ├── main.py                 # create_app, lifespan (relay, consumer, expiration), handlers
│   ├── config.py               # Settings(BaseAppSettings): DB, Kafka, TTL, outbox-тюнинг
│   ├── database.py             # async engine, async_session_maker, Base, get_db
│   ├── kafka.py                # AIOKafkaProducer + publish_envelope (топик events)
│   ├── metrics.py              # reservations_total, outbox_pending/failures, expiration
│   ├── errors.py               # IntegrityErrorMapper (PG → HTTP codes)
│   ├── api/
│   │   ├── stock.py            # /stock-items (CRUD + adjustments + threshold)
│   │   ├── availability.py     # /availability/{sku}, POST /availability/check
│   │   └── reservations.py     # /reservations (+confirm/release, Idempotency-Key)
│   ├── schemas/
│   │   ├── inventory.py        # Pydantic-схемы (available — производное поле)
│   │   └── saga.py             # команды саги (reserve/confirm/release)
│   ├── models/
│   │   ├── inventory.py        # StockItem, Reservation, ProcessedCommand
│   │   └── outbox.py           # InventoryOutbox: envelope JSONB, status, attempt_count
│   ├── repositories/
│   │   ├── stock_repo.py       # create/get/list/adjust (условный UPDATE)/threshold
│   │   └── reservation_repo.py # reserve/confirm/release/expire (атомарные UPDATE)
│   └── services/
│       ├── stock.py            # транзакционная граница + outbox события склада
│       ├── availability.py     # только чтение, без побочных эффектов
│       ├── reservations.py     # жизненный цикл резервов + outbox + метрики
│       ├── events.py           # конверты EventEnvelope, enqueue_event, low-stock check
│       ├── saga.py             # обработчик команд саги (идемпотентность по event_id)
│       ├── expiration.py       # задание истечения (FOR UPDATE SKIP LOCKED)
│       ├── relay.py            # outbox → Kafka (батчи, backoff, ретенция, breaker)
│       ├── consumer.py         # aiokafka-потребитель команд (ручной commit)
│       └── breaker.py          # CircuitBreaker + relay_breaker
└── tests/                      # unit + Testcontainers (PostgreSQL, Kafka)
```

## Конфигурация

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/mini_mall_inventory` | Асинхронный URL PostgreSQL |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Адреса брокеров Kafka |
| `COMMANDS_TOPIC` | `inventory.commands` | Командный топик саги (reserve/confirm/release) |
| `EVENTS_TOPIC` | `inventory.events` | Событийный топик (исходы команд + события склада) |
| `CONSUMER_GROUP` | `inventory-service` | Consumer group потребителя команд |
| `RESERVATION_DEFAULT_TTL_SECONDS` | `900` | TTL резерва по умолчанию (сек) |
| `EXPIRATION_INTERVAL` | `30.0` | Пауза задания истечения (сек) |
| `EXPIRATION_BATCH_SIZE` | `100` | Макс. резервов за один проход истечения |
| `AVAILABILITY_BATCH_MAX_SKUS` | `100` | Лимит SKU в пакетной проверке доступности (сверх — 422) |
| `OUTBOX_POLL_INTERVAL` | `1.0` | Интервал сканирования outbox (сек) |
| `OUTBOX_MAX_ATTEMPTS` | `10` | Макс. число попыток публикации (строка остаётся observable) |
| `OUTBOX_BACKOFF_BASE` | `1.0` | База экспоненциальной задержки (сек) |
| `OUTBOX_RETENTION_SECONDS` | `86400` | Срок жизни обработанных строк outbox; `0` — без чистки |
| `BREAKER_FAILURE_THRESHOLD` | `5` | Порог подряд идущих отказов для breaker релея |
| `BREAKER_OPEN_SECONDS` | `30.0` | Время открытого состояния breaker (сек) |
| `KAFKA_PUBLISH_TIMEOUT` | `5.0` | Таймаут публикации в Kafka (сек) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *(пусто)* | OTLP/HTTP endpoint трейсов (Jaeger); пусто — tracing выключен |

## База данных

### `stock_items`

| Поле | Тип | Свойства |
|---|---|---|
| `id` | UUID | PK |
| `catalog_product_id` | UUID | nullable, opaque-ссылка на продукт каталога |
| `sku` | VARCHAR(64) | UNIQUE, indexed |
| `quantity_on_hand` | INTEGER | CHECK `>= 0` |
| `quantity_reserved` | INTEGER | CHECK `>= 0`, CHECK `<= quantity_on_hand` |
| `low_stock_threshold` | INTEGER | CHECK `>= 0`, default `0` (оповещения выключены) |
| `created_at` / `updated_at` | TIMESTAMP(tz) | UTC |

`available` — производное поле (`on_hand - reserved`), никогда не хранится.

### `reservations`

| Поле | Тип | Свойства |
|---|---|---|
| `id` | UUID | PK |
| `stock_item_id` | UUID | FK → `stock_items.id` ON DELETE RESTRICT |
| `quantity` | INTEGER | CHECK `> 0` |
| `status` | VARCHAR(16) | `active`/`confirmed`/`released`/`expired` (CHECK-домен) |
| `holder_ref` | VARCHAR(255) | nullable, владелец резерва (id заказа/корзины) |
| `idempotency_key` | VARCHAR(255) | nullable, UNIQUE |
| `expires_at` | TIMESTAMP(tz) | момент истечения |
| `created_at` / `updated_at` | TIMESTAMP(tz) | UTC |

Частичный индекс `ix_reservations_active_expires_at` (`expires_at WHERE
status='active'`) — для задания истечения.

### `processed_commands`

| Поле | Тип | Свойства |
|---|---|---|
| `event_id` | UUID | PK — идемпотентность потребителя команд |
| `processed_at` | TIMESTAMP(tz) | UTC |

### `inventory_outbox`

| Поле | Тип | Свойства |
|---|---|---|
| `id` | BIGSERIAL | PK |
| `event_id` | UUID | UNIQUE |
| `envelope` | JSONB | конверт `common.events.EventEnvelope` |
| `status` | VARCHAR(32) | `pending` → `processed` |
| `attempt_count` | INTEGER | начальное 0 |
| `last_error` | TEXT | nullable, до 500 символов |
| `created_at` / `processed_at` | TIMESTAMP(tz) | |

### Миграции

```bash
cd services/inventory
DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/mini_mall_inventory" \
  ../../.venv/bin/alembic upgrade head
```

Приложение не создаёт и не изменяет схему на старте — только миграции Alembic.

## API

### Склад (`/stock-items`)

| Метод | Описание |
|---|---|
| `POST /stock-items` | Создать позицию; 201, 409 DUPLICATE_SKU («Stock item SKU already exists») |
| `GET /stock-items` | Список с пагинацией (`?offset=`, `?limit=`, total) |
| `GET /stock-items/by-sku/{sku}` | По SKU; 404 STOCK_ITEM_NOT_FOUND (регистрируется **до** `/{id}`) |
| `GET /stock-items/{id}` | По id; 404 STOCK_ITEM_NOT_FOUND |
| `PATCH /stock-items/{id}` | Обновить порог low-stock; 404 |
| `POST /stock-items/{id}/adjustments` | Корректировка `{delta, reason}`; 404, 422 (on_hand < 0) |

Каждый ответ содержит `available = quantity_on_hand - quantity_reserved`.

### Доступность (`/availability`, только чтение)

| Метод | Описание |
|---|---|
| `GET /availability/{sku}` | `{sku, quantity_on_hand, quantity_reserved, available, in_stock}`; 404 для неизвестного SKU |
| `POST /availability/check` | Батч `{skus: [...]}`; по элементу на каждый SKU (`found: false` — SKU неизвестен); размер списка > `AVAILABILITY_BATCH_MAX_SKUS` → 422 |

Эндпоинты доступности не изменяют состояние.

### Резервы (`/reservations`)

| Метод | Описание |
|---|---|
| `POST /reservations` | Создать `{sku, quantity, holder_ref, ttl_seconds?}`; 201, 404 STOCK_ITEM_NOT_FOUND, 409 INSUFFICIENT_STOCK. Заголовок `Idempotency-Key` сохраняется как ключ идемпотентности: повтор возвращает исходный резерв |
| `POST /reservations/{id}/confirm` | Подтвердить (списывает on_hand и reserved); 409 INVALID_RESERVATION_STATE для не-active; повторный confirm — идемпотентный |
| `POST /reservations/{id}/release` | Освободить (возвращает reserved); семантика как у confirm |
| `GET /reservations/{id}` | Статус, expires_at, holder_ref; 404 RESERVATION_NOT_FOUND |

## Защита от перепродажи

Резерв выполняется одним атомарным условным UPDATE (минимальное окно
блокировки, перепродажа невозможна по построению):

```sql
UPDATE stock_items
SET quantity_reserved = quantity_reserved + :qty
WHERE id = :id AND quantity_on_hand - quantity_reserved >= :qty
RETURNING id;
```

Ноль совпавших строк → `409 INSUFFICIENT_STOCK`. CHECK-ограничение
`quantity_reserved <= quantity_on_hand` — вторая линия обороны на уровне БД.
Confirm/release/expiration используют аналогичные условные UPDATE.

## Жизненный цикл резервов

- `active` → `confirmed` (confirm): списываются и `on_hand`, и `reserved`.
- `active` → `released` (release): возвращается `reserved`.
- `active` → `expired`: фоновое задание (asyncio-задача в `lifespan`, интервал
  `EXPIRATION_INTERVAL`) выбирает просроченные `active`-резервы
  `FOR UPDATE SKIP LOCKED`, возвращает склад и пишет событие — одной
  транзакцией на пачку. `SKIP LOCKED` пропускает резерв, который
  конкурентная транзакция прямо сейчас подтверждает.
- Повторное применение уже применённой операции возвращает текущее состояние
  без второго изменения; операции над `confirmed`/`released`/`expired`
  → `409 INVALID_RESERVATION_STATE`.

## Контракт саги (checkout)

Order Service (Saga Orchestrator) — вне этого сервиса; инвентарь реализует
только сторону участника.

**Команды** (`COMMANDS_TOPIC`, consumer group `CONSUMER_GROUP`): значение
сообщения — конверт с полями команды:

```json
{
  "event_id": "<uuid>",
  "command": "reserve|confirm|release",
  "order_id": "order-123",
  "items": [{"sku": "SKU-1", "quantity": 2}],
  "saga_ref": "saga-1",
  "correlation_id": "<uuid>"
}
```

- `reserve` — заказ начался: один резерв на пару (order, sku).
- `confirm` — заказ успешен: подтверждение активных резервов.
- `release` — компенсация: освобождение; резерв, который уже истёк,
  трактуется как идемпотентный успех (склад уже возвращён).

**Исходы** (в `EVENTS_TOPIC`, через outbox, в той же транзакции, что и
изменение состояния): `inventory.reserved`, `inventory.reservation_failed`,
`inventory.confirmed`, `inventory.released`.

**Идемпотентность**: строка `processed_commands` (PK `event_id`) вставляется
в той же транзакции, что и изменение состояния; повторная доставка
(уникальный `event_id`) аккается без повторной обработки. Offset коммитится
вручную после успешной обработки.

## Outbox и релей

1. Каждое изменение состояния с внешним событием (создание позиции,
   корректировка, порог, резерв/confirm/release/истечение, low-stock) пишет
   `EventEnvelope` в `inventory_outbox` в той же транзакции. Откат
   транзакции не оставляет ни изменения, ни события.
2. Фоновый релей (asyncio-задача) раз в `OUTBOX_POLL_INTERVAL` публикует
   пачку `pending`-конвертов в `EVENTS_TOPIC` (ключ = `event_id`) под
   защитой `relay_breaker`, затем помечает `processed`.
3. Задержка между попытками — экспоненциальная
   (`base * 2**(attempt-1)`); после `OUTBOX_MAX_ATTEMPTS` строка остаётся
   `pending` с `last_error` (observable, не блокирует очередь).
4. Обработанные строки чистятся по ретенции `OUTBOX_RETENTION_SECONDS`.

Недоступность Kafka никогда не ломает синхронный путь: события просто
накапливаются и публикуются после восстановления.

## Low-stock оповещения

Stateless-проверка пересечения порога внутри той же транзакции каждого
уменьшения доступности: событие `inventory.low_stock` эмитится тогда и
только тогда, когда `available_before >= threshold > available_after`.
Порог `0` выключает оповещения. Пока SKU ниже порога — новые уменьшения не
переэмитят; restock выше порога неявно «перезаряжает» оповещение (флаги
не хранятся — дрейфа состояния нет).

## Метрики (`/metrics`)

- `inventory_reservations_total{outcome=reserved|insufficient|confirmed|released}` — исходы операций с резервами.
- `inventory_outbox_pending` — текущее число `pending`-строк outbox.
- `inventory_outbox_failures_total` — строки, исчерпавшие попытки публикации.
- `inventory_expiration_runs_total` / `inventory_expiration_processed_total` — проходы задания истечения.
- Общие HTTP-счётчики/latency — от `common.middleware.PrometheusMetricsMiddleware`.

Health: `GET /health/live` (200), `GET /health/ready` (проверка `SELECT 1`,
503 при недоступности PostgreSQL).

## Тестирование

```bash
cd services/inventory
../../.venv/bin/pytest tests/ -q   # unit + интеграционные (Testcontainers PG + Kafka)
```

- **Unit**: конфигурация (defaults/env), каталог ошибок и маппер
  `IntegrityError`, границы валидации схем, команды саги (parse/отказ),
  stateless low-stock crossing, circuit breaker, health-эндпоинты
  (движок-заглушка), метрики.
- **PostgreSQL интеграционные** (Testcontainers `postgres:16-alpine` + реальные
  миграции Alembic): CRUD и корректировки, доступность (включая отсутствие
  побочных эффектов), резервы и **конкурентный no-oversell тест** (20
  параллельных резервов по 10 при available 100 → ровно 10 успешных),
  жизненный цикл (confirm/release/истечение/инварианты), контракт саги
  (идемпотентность `event_id`, компенсация истёкшего резерва), outbox на всех
  записывающих путях + rollback-тест, low-stock события, метрики.
- **Kafka интеграционные** (Testcontainers `cp-kafka:7.6.0`): потребитель
  команд (state-изменения, повторная доставка без двойного эффекта), релей
  (публикация ровно один раз, отметка processed), outage-семантика
  (недоступный Kafka не ломает API, backlog публикуется после
  восстановления), poison-строка (max-attempts, last_error, очередь не
  блокируется), low-stock end-to-end через релей.

## Контейнеризация и запуск

```bash
# локально:
cd services/inventory && ../../.venv/bin/uvicorn app.main:app --reload --port 8200

# Docker (из корня репозитория) и стек:
docker compose -f infrastructure/docker-compose.yml up inventory-service
```

В compose сервис зарегистрирован с собственной БД `mini_mall_inventory`
(создаётся `infrastructure/initdb/01-create-inventory-db.sh` при первой
инициализации тома PostgreSQL), healthcheck-ом и зависимостями от postgres/kafka.
Миграции применяет одноразовый контейнер `inventory-migrate` (тот же образ,
команда `alembic upgrade head`): `inventory-service` стартует только после его
успешного завершения (`service_completed_successfully`).

## Связанные документы

- OpenSpec `inventory-service`: `openspec/changes/inventory-service/`
- Общая библиотека: [libs-common.md](../libs-common.md)
- Архитектура: [architecture.md](../architecture.md)
