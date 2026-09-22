# Сервис аутентификации (`services/auth`)

Автономный микросервис аутентификации: пользователи, пароли (bcrypt),
JWT access-токены и непрозрачные refresh-токены с безопасной ротацией и
детекцией повторного использования.

База данных сервиса изолирована (`mini_mall_auth`), связь с другими
сервисами — только по HTTP через шлюз или напрямую.

## Структура

```text
services/auth/
├── pyproject.toml        # зависимости, pytest-asyncio, uv-источники common
├── Dockerfile            # multi-stage, сборка из корня репо
├── alembic.ini           # prepend_sys_path = . (пакет app)
├── alembic/
│   ├── env.py            # async-движок, URL из настроек сервиса
│   └── versions/
│       └── 0001_initial.py  # users + refresh_tokens
├── app/
│   ├── main.py           # FastAPI app, health, metrics, обработчики ошибок
│   ├── config.py         # Settings(BaseAppSettings)
│   ├── database.py       # engine, async_session_maker, Base, get_db
│   ├── api/auth.py       # эндпоинты /api/v1/auth/..., /users/me
│   ├── models/user.py    # User, RefreshToken
│   ├── repositories/auth_repo.py  # доступ к данным, FOR UPDATE
│   ├── schemas/auth.py   # Pydantic-схемы
│   └── services/
│       ├── security.py   # bcrypt + JWT (HS256)
│       └── token.py      # непрозрачные токены + SHA-256
└── tests/
    ├── test_security.py  # юнит-тесты безопасности
    └── test_auth.py      # интеграционные тесты (Testcontainers)
```

## Конфигурация

`app/config.py` наследует `common.config.BaseAppSettings` и добавляет поля
сервиса (см. [Быстрый старт](getting-started.md) — таблица переменных).

Ключевое: `JWT_SECRET` задаётся в production явно и должен быть **≥ 32 байт**
(иначе PyJWT предупреждает об ослабленной подписи). В `production` сервис
отказывается стартовать с дефолтным `JWT_SECRET` и без `GATEWAY_SECRET`
(`app/config.py`, `Settings._production_requires_real_secrets`).

`GATEWAY_SECRET` — общий секрет API Gateway для доверенных заголовков
`X-User-ID`/`X-User-Roles` (`GET /users/me`). Если он задан, запрос обязан
предъявить его в `X-Gateway-Secret`, иначе — `401 INVALID_GATEWAY_SECRET`.
Пустое значение — только для development (доверие без проверки).

## База данных

Модели — `app/models/user.py`:

### `users`

| Поле | Тип | Свойства |
| --- | --- | --- |
| `id` | UUID | PK, по умолчанию `uuid.uuid4` |
| `email` | VARCHAR(255) | UNIQUE, индекс |
| `password_hash` | VARCHAR(255) | bcrypt `$2b$...` |
| `roles` | JSON | например `["customer"]` |
| `is_active` | BOOLEAN | флаг активности |
| `created_at` / `updated_at` | TIMESTAMP(tz) | UTC, автозаполнение |

### `refresh_tokens`

| Поле | Тип | Свойства |
| --- | --- | --- |
| `id` | UUID | PK |
| `user_id` | UUID | FK → `users.id` ON DELETE CASCADE |
| `token_hash` | VARCHAR(255) | SHA-256 непрозрачного токена, UNIQUE |
| `expires_at` | TIMESTAMP(tz) | UTC |
| `is_revoked` | BOOLEAN | признак отзыва |
| `created_at` | TIMESTAMP(tz) | UTC |

> В БД хранится **только хэш** refresh-токена: даже утечка базы не позволяет
> использовать токены клиентов.

### Миграции

```bash
cd services/auth
../.venv/bin/alembic upgrade head            # применить
../.venv/bin/alembic upgrade head --sql      # показать SQL без применения
../.venv/bin/alembic revision --autogenerate -m "..."   # новая миграция
```

URL берётся из `app.config.settings.database_url` (переменные окружения
/ `.env`). Файл настроен на путешествие: `prepend_sys_path = .`.

## Безопасность

### Пароли

`hash_password`/`verify_password` в `app/services/security.py` используют
**bcrypt напрямую** (не через passlib): начиная с bcrypt 5.x passlib
несовместим и вызывает ошибки. Отклонение от исходной спецификации OpenSpec
(там был `passlib[bcrypt]`) зафиксировано в docstrings модуля.

- Хэш: `$2b$...` с уникальной солью.
- Проверка: `bcrypt.checkpw`. Значение заведомо неверного хэша не ломает
  проверку (`ValueError` → `False`).

### Access-токен (JWT)

- Алгоритм: **HS256**, ключ — `JWT_SECRET`.
- Claims: `sub` (UUID), `roles`, `exp`, `iat`, `jti`. **Никакого PII**.
- TTL: `ACCESS_TOKEN_EXPIRE_MINUTES` (по умолчанию 15).

### Refresh-токен

- Генерация: `secrets.token_urlsafe(64)` (`app/services/token.py`).
- TTL: `REFRESH_TOKEN_EXPIRE_DAYS` (по умолчанию 7).
- Хранение: SHA-256 хэш в БД.

### Ротация и конкуренция

`POST /auth/refresh` читает строку токена через
`SELECT ... FOR UPDATE` (`repositories.auth_repo.get_refresh_token_for_update`),
поэтому при двух одновременных запросах с одним токеном успешен только один —
второй получит `401`.

**Reuse detection**: если на `/auth/refresh` пришёл уже отозванный токен,
отзываются **все** токены пользователя, а запрос завершается `401`.

## API

Префикс: `/api/v1`.

### `POST /auth/register`

`{email, password(min 8)}` → `201` профиль пользователя.
Дубликат email → `409 DUPLICATE_EMAIL`.

### `POST /auth/login`

`{email, password}` → `200 {access_token, refresh_token, token_type: "bearer"}`.
Неверные данные / неактивный пользователь → `401 INVALID_CREDENTIALS`.

### `POST /auth/refresh`

`{refresh_token}` → `200` новая пара токенов.
Ошибки → `401` c кодами: `INVALID_REFRESH_TOKEN`, `TOKEN_REUSE_DETECTED`,
`EXPIRED_REFRESH_TOKEN`, `INACTIVE_USER`.

### `POST /auth/logout`

`{refresh_token}` → всегда `204` (идемпотентно). После логаута refresh с этим
токеном вернёт `401`.

### `GET /users/me`

Заголовок `Authorization: Bearer <access_token>` → `200` профиль
`{id, email, roles}`. Иначе → `401`.

### Обработка ошибок

Единый формат `ErrorResponse` из `common`:

```json
{
  "error": {"code": "INVALID_CREDENTIALS", "message": "...", "details": null},
  "request_id": "7f9c..."
}
```

- Провал валидации → `422 VALIDATION_ERROR` с `details` от Pydantic.
- Необработанное исключение → `500 INTERNAL_ERROR`.

### Health и метрики

- `GET /health/live` → `{"status": "alive"}`.
- `GET /health/ready` → `{"status": "ready"}` при успешном `SELECT 1`, иначе
  `503`.
- `GET /metrics` → метрики Prometheus.

## Тестирование

```bash
cd services/auth
../.venv/bin/pytest tests/
```

Тесты (11) запускаются **без** `PYTHONPATH` — пакет `app.*` импортируется из
каталога сервиса:

- `test_security.py` — юнит (bcrypt, JWT, токены);
- `test_auth.py` — интеграционные на Testcontainers: регистрация/логин,
  ротация, **конкурентная ротация** (ровно один `200`), reuse detection
  (отзыв всех токенов), идемпотентный логаут, health.

Итоговая сессия pytest настроена в `pyproject.toml`:
`asyncio_mode = "strict"`, session-scope для фикстур.

## Контейнеризация и запуск

См. [Контейнеризация](docker.md) и [Быстрый старт](getting-started.md).

```bash
# локально:
cd services/auth && ../.venv/bin/uvicorn app.main:app --reload --port 8000

# Docker (из корня репозитория):
docker build -f services/auth/Dockerfile -t auth-service .
docker run -p 8000:8000 -e DATABASE_URL=... -e JWT_SECRET=... auth-service
```

## Связанные документы

- OpenSpec `01-auth-service`: `openspec/changes/01-auth-service/`.
- Общая библиотека: [libs-common.md](../libs-common.md).