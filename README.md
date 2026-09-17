# mini_mall_2

Платформа для e-commerce: набор автономных микросервисов на **Python 3.12 / FastAPI**,
объединённых в монорепозиторий с локальной линковкой общих библиотек.

## Кратко

- **Микросервисы** (`services/`): каждый сервис автономен — у него собственные
  `pyproject.toml`, `Dockerfile`, БД, миграции и тесты. Сервисы**не импортируют** доменную логику друг друга.
- **Общая библиотека** (`libs/common`): пакет `common` — только инфраструктура
  (конфигурация, логирование, метрики, ошибки, события). Подключается как обычная
  установленная зависимость.
- **API Gateway** (`gateway/`), **инфраструктура** (`infrastructure/`), **OpenSpec** (`openspec/`).

Главная документация — в каталоге [`docs/`](docs/README.md).

```text
mini_mall_2/
├── gateway/             # API-шлюз
├── libs/common/         # пакет common (общая инфраструктура)
├── services/
│   ├── auth/            # автономный сервис аутентификации
│   └── template/        # шаблон нового сервиса
├── infrastructure/      # docker-compose и инфраструктурные Dockerfile
├── tests/               # сквозные тесты платформы (Testcontainers)
├── openspec/            # спецификации проекта
└── docs/                # исчерпывающая документация на русском
```

## Быстрый старт

```bash
python -m venv .venv
.venv/bin/pip install -e .[dev]      # dev-инструменты из корня
.venv/bin/pip install -e libs/common # общая библиотека (editable)
cp services/auth/.env.example services/auth/.env   # если есть
```

Подробно: [`docs/getting-started.md`](docs/getting-started.md).

## Связаться с сервисами

- Сервис аутентификации: `http://localhost:8000`, документация OpenAPI — `/docs`.

## TOC документации

| Раздел | Содержание |
| --- | --- |
| [Обзор](docs/README.md) | Карта документации |
| [Архитектура](docs/architecture.md) | Принципы, границы, структура репозитория |
| [Быстрый старт](docs/getting-started.md) | Установка, тесты, запуск |
| [Общая библиотека](docs/libs-common.md) | Пакет `common`, подключение, правила |
| [Сервис auth](docs/services/auth.md) | Конфигурация, БД, API, безопасность, тесты |
| [Контейнеризация](docs/docker.md) | Dockerfile, сборка, compose |
| [Генерация API-документации](docs/code-reference.md) | pdoc из docstrings |