# Генерация API-документации из docstrings

Код покрыт docstrings (на русском), поэтому документацию по API можно
генерировать автоматически. Используется **pdoc** — лёгкий генератор,
работающий без конфигурации Sphinx.

## Установка

pdoc добавлен в dev-зависимости корневого `pyproject.toml`:

```bash
.venv/bin/pip install -e .[dev]
# или точечно:
.venv/bin/pip install pdoc
```

## Генерация

Из корня репозитория:

```bash
# общая библиотека common:
.venv/bin/pdoc common --output-dir docs/api/common

# пакет app сервиса auth (импортируется из services/auth):
(cd services/auth && ../.venv/bin/pdoc app --output-dir ../../docs/api/auth)
```

Или одной командой `make docs` (см. Makefile):

```bash
make docs
```

Результат — статические HTML-страницы в `docs/api/<package>/`, которые можно
открыть в браузере (`file://...`) или положить на любой хостинг.

## Как устроены docstrings

- Каждый модуль начинается с однострочного описания с точкой.
- Классы и функции — с описанием, разделом «Параметры» (`Параметры:`),
  «Возвращает» (`Возвращает:`) и «Исключения» (`Исключения:`), когда уместно.
- Имена пакетов/модулей в тексте — в backticks (`` `app.main` ``),
  перекрёстные ссылки — `:class:` / `:func:`.

pdoc рендерит эти секции автоматически; кастомные форматы (Google, NumPy)
также поддерживаются, но принят единый стиль выше — соблюдайте его в новом коде.

## Что покрыто docstrings

| Пакет | Модули |
| --- | --- |
| `common` | `__init__`, `config`, `errors`, `events`, `logging`, `middleware`, `observability` |
| `app` (auth) | `main`, `config`, `database`, `api/auth`, `models/user`, `repositories/auth_repo`, `schemas/auth`, `services/security`, `services/token` |
| прочее | `services/template/app/main.py`, `services/auth/alembic/`, файлы тестов |

## Чекать docstring при сборке

Линная проверка docstrings правилом pydocstyle (D-серия ruff) пока не
включена намеренно: чтобы не блокировать рефакторинг существующих
предсуществующих ворнингов (B008/BLE001/B006). Когда захотите — включите в
`pyproject.toml` правило `D` и прогоните `ruff check --fix`.

## Связанные разделы

- [Общая библиотека `common`](libs-common.md)
- [Сервис `auth`](services/auth.md)