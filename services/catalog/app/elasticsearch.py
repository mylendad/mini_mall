"""Elasticsearch: клиент, имя индекса и идемпотентное создание mapping.

Elasticsearch здесь — производная поисковая проекция; PostgreSQL остаётся
единственной системой записи. Индекс ``catalog_products_v1`` создаётся
идемпотентно на старте приложения и автономной командой
``python -m app.elasticsearch`` (см. D5).

Клиент намеренно без ретраев на таймаут (``max_retries=0``,
``retry_on_timeout=False``): повторные попытки и восстановление далают
circuit-breaker (см. :mod:`app.services.breaker`).
"""

from __future__ import annotations

import asyncio

from elasticsearch import AsyncElasticsearch

from app.config import settings

#: Полное имя индекса продуктов каталога (версионировано).
CATALOG_INDEX = f"{settings.es_index_prefix}_v1"

#: Явный mapping по D5: keyword для точных фильтров/сортировки, text для
#: полнотекстового поиска, scaled_float для цены, flattened для атрибутов.
INDEX_MAPPING: dict = {
    "properties": {
        "id": {"type": "keyword"},
        "sku": {"type": "keyword"},
        "name": {
            "type": "text",
            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
        },
        "description": {"type": "text"},
        "category_id": {"type": "keyword"},
        "category_name": {"type": "keyword", "ignore_above": 256},
        "price": {"type": "scaled_float", "scaling_factor": 100},
        "currency": {"type": "keyword"},
        "attributes": {"type": "flattened"},
        "is_active": {"type": "boolean"},
        "created_at": {"type": "date"},
        "updated_at": {"type": "date"},
    }
}


def create_client(
    url: str | None = None,
    *,
    request_timeout: float | None = None,
) -> AsyncElasticsearch:
    """Создаёт клиент ES с таймаутом из настроек и без внутренних ретраев.

    ``request_timeout`` можно переопределить (тесты дают более щедрое
    значение на холодном старте контейнера).
    """
    return AsyncElasticsearch(
        hosts=[url or settings.elasticsearch_url],
        request_timeout=request_timeout or settings.es_request_timeout,
        max_retries=0,
        retry_on_timeout=False,
    )


es_client = create_client()


async def ensure_index(client: AsyncElasticsearch | None = None) -> bool:
    """Идемпотентно создаёт индекс ``CATALOG_INDEX`` с mapping по D5.

    Возвращает:
        ``True``, если индекс был создан; ``False``, если уже существовал
        (``resource_already_exists_exception``).
    """
    client = client or es_client
    already = await client.indices.exists(index=CATALOG_INDEX)
    if already:
        return False
    await client.indices.create(
        index=CATALOG_INDEX,
        mappings=INDEX_MAPPING,
        settings={"number_of_shards": 1, "number_of_replicas": 0},
    )
    return True


async def delete_index(client: AsyncElasticsearch | None = None) -> bool:
    """Удаляет индекс ``CATALOG_INDEX``, если он существует (404 игнорируется)."""
    client = client or es_client
    removed = await client.indices.exists(index=CATALOG_INDEX)
    if removed:
        await client.indices.delete(index=CATALOG_INDEX)
    return removed


async def _main() -> None:
    """Автономный запуск: ``python -m app.elasticsearch`` создаёт индекс."""
    created = await ensure_index()
    print(f"index={CATALOG_INDEX} created={created}")
    await es_client.close()


if __name__ == "__main__":
    asyncio.run(_main())
