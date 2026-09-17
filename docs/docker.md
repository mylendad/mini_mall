# Контейнеризация

## Принципы

- **Сборка из корня репозитория.** Контекст — весь монорепозиторий, чтобы
  образ мог собрать общую библиотеку `common` рядом с сервисом.
- **Multi-stage.** В первом стейдже собираются wheel-пакеты, во втором они
  только устанавливаются — рантайм без инструментов сборки и меньше по размеру.
- **Не-root.** Внутри контейнера запускается непривилегированный пользователь
  `appuser`.
- **Короткий CMD.** `uvicorn app.main:app` — без длинных путей в духе
  `services.auth.app.main:app`.

## Ключевые файлы

- `services/auth/Dockerfile` — Dockerfile сервиса аутентификации.
- `.dockerignore` (в корне) — исключает `.venv/`, `openspec/`, кэши и т.п. из
  контекста сборки.
- `infrastructure/docker-compose.yml` — инфраструктурные контейнеры
  (postgres, redis, kafka, mongodb, elasticsearch, clickhouse).

## Сервис `auth`: как работает Dockerfile

```dockerfile
# STAGE 1: builder — только сборка колес
FROM python:3.12-slim AS builder
WORKDIR /build
COPY libs/common ./libs/common
RUN pip wheel --no-cache-dir --no-deps --wheel-dir=/wheels ./libs/common

COPY services/auth ./services/auth
WORKDIR /build/services/auth
RUN pip wheel --no-cache-dir --no-deps --wheel-dir=/wheels .

# STAGE 2: runtime — только установка колес
FROM python:3.12-slim
WORKDIR /app/services/auth
RUN useradd -m -u 1000 appuser
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Шаги:

1. Собирается wheel пакета `common` (`libs/common`), затем wheel сервиса
   (`services/auth`). `--no-deps` означает: стороны не тянут зависимости из
   сети на этапе builder — их подтянет финальный `pip install`, а зависимость
   `common>=0.1.0` будет удовлетворена положенным рядом колесом `common`.
2. В рантайм копируются только два wheel-пакета и устанавливаются: образ
   получает `app`, `common` и все зависимости из PyPI.
3. Приложение запускается под `appuser` из `WORKDIR /app/services/auth`,
   `uvicorn app.main:app` импортирует `app.main` из site-packages.

### Сборка и запуск

```bash
# из корня репозитория:
docker build -f services/auth/Dockerfile -t auth-service .

docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/mini_mall_auth \
  -e JWT_SECRET="..." \
  auth-service
```

### Проверка

```bash
curl localhost:8000/health/live   # {"status":"alive"}
curl localhost:8000/health/ready  # {"status":"ready"} при живом Postgres
curl localhost:8000/docs          # Swagger
curl localhost:8000/metrics       # метрики Prometheus
```

## `.dockerignore`

В корне исключены: `.git/`, `.gitignore`, `.venv/`, `.opencode/`, `openspec/`,
кэши Python (`__pycache__`, `.pytest_cache`, `.ruff_cache`), сборки
(`dist/`, `build/`, `*.egg-info/`), `*.md`, `.env`.

> `.env` исключается для того, чтобы секреты из переменных окружения не
> попадали в образ и контекст сборки.

## Инфраструктурный compose

`infrastructure/docker-compose.yml` поднимает: PostgreSQL 16, Redis 7, Kafka
(confluentinc/cp-kafka 7.6, single-node KRaft), MongoDB 7, Elasticsearch 8,
ClickHouse.

```bash
docker compose -f infrastructure/docker-compose.yml up -d
```

Инфраструктурные контейнеры содержат только middleware (No бизнес-кода).
Сервисы подключаются к ним по сети compose в дальнейшем шаге деплоя.

## Разница с шаблонным Dockerfile

В `infrastructure/Dockerfile` живёт более ранний шаблон (сборка через uv,
`uvicorn services.template.app.main:create_app --factory`). Он относится к
концепции «сервис-пакет в монорепо-иерархии» и для новых сервисов
не рекомендуется: используйте подход `services/<name>/Dockerfile` +
`app.main:app` (см. [architecture.md](architecture.md)).