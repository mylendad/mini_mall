# Быстрый старт

## Требования

- **Python 3.12+**
- Рекомендуется `uv` (для работы с `[tool.uv.sources]`), но базовый поток
  работает на чистом `pip`
- Docker (для интеграционных тестов через Testcontainers и сборки образов)

## 1. Виртуальное окружение и зависимости

```bash
cd mini_mall_2
python -m venv .venv

# dev-инструменты платформы (pytest, ruff, pdoc, testcontainers...) из корня:
.venv/bin/pip install -e .[dev]

# общая библиотека common (editable — изменения подхватываются сразу):
.venv/bin/pip install -e libs/common
```

Или через uv:

```bash
uv sync
```

> Примечание: сервис аутентификации устанавливается отдельно — см. следующий
> раздел. Для локальной разработки достаточно того, чтобы пакет `app` был
> доступен из каталога `services/auth`.

## 2. Проверка инструментов

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```

## 3. Сервис аутентификации

Рабочий каталог — `services/auth`.

```bash
cd services/auth

# тесты (без PYTHONPATH — пакет app.* импортируется из текущего каталога):
../.venv/bin/pytest tests/

# запуск сервиса:
../.venv/bin/uvicorn app.main:app --reload --port 8000
```

Открыть Swagger: <http://localhost:8000/docs>.

### Переменные окружения (все опциональны)

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/mini_mall_auth` | URL асинхронного подключения к PostgreSQL |
| `JWT_SECRET` | `super-secret-jwt-key-change-in-production-1234567890` | Секрет для HS256 (в production обязательно задать ≥32 байт) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | TTL access-токена |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | TTL refresh-токена |
| `APP_NAME` | `auth-service` | Имя сервиса |
| `LOG_LEVEL` | `INFO` | Уровень логирования |

## 4. Инфраструктура (PostgreSQL, Kafka, Redis и т.д.)

Для локального запуска сервиса с реальной БД поднимите инфраструктуру:

```bash
docker compose -f infrastructure/docker-compose.yml up -d
```

Затем примените миграции:

```bash
cd services/auth
../.venv/bin/alembic upgrade head
```

## 5. Частая проверка состояния

```bash
make lint     # ruff по всей платформе
make test     # pytest из корня
make docs     # генерация API-документации (pdoc), см. code-reference.md
```

## Куда дальше

- [Архитектура](architecture.md)
- [Сервис `auth`](services/auth.md)
- [Общая библиотека `common`](libs-common.md)