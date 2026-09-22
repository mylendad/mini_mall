# Документация платформы mini_mall

Исчерпывающая документация проекта на русском языке. Короткая сводка — в
[корневом README](../README.md).

## Карта разделов

| Раздел | Зачем читать |
| --- | --- |
| [Архитектура](architecture.md) | Принципы платформы, границы сервисов, монорепо и линковка пакетов |
| [Быстрый старт](getting-started.md) | Установка окружения, тесты, локальный запуск сервиса |
| [Общая библиотека `common`](libs-common.md) | Что лежит в `libs/common`, как сервисы её подключают, правила расширения |
| [Сервис `auth`](services/auth.md) | Назначение, конфигурация, БД, API, безопасность, тесты, миграции |
| [Сервис `catalog`](services/catalog.md) | Каталог продуктов и категорий: PG → ES синхронизация (outbox), поиск, admin-reindex, тесты |
| [Контейнеризация](docker.md) | Multi-stage Dockerfile, сборка из корня, compose |
| [Генерация API-документации](code-reference.md) | pdoc: как сгенерировать документацию из docstrings |
| [ADR](adr/0001-catalog-service-review.md) | Реестр архитектурных решений (результаты ревью): [ADR-0001: catalog-service](adr/0001-catalog-service-review.md), [ADR-0002: auth-service](adr/0002-auth-service-review.md) |

## Соглашения

- Домашняя документация по коду (docstrings) — на русском, чтобы сгенерированные
  страницы были единообразными.
- Все команды предполагают POSIX-шелл. Виртуальное окружение — `.venv` в корне репозитория.
- Решения по архитектуре фиксируются в [`openspec/`](../openspec).

## Связанные документы

- OpenSpec: [`openspec/README.md`](../openspec/README.md)
- Спецификация foundation: [`openspec/specs/foundation/spec.md`](../openspec/specs/foundation/spec.md)