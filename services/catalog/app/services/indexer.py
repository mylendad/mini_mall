"""Индексация продуктов в Elasticsearch (производная проекция PostgreSQL).

Документы строятся только из закоммиченных строк БД — релей и реиндекс
всегда перечитывают авторитетное состояние продукта и не доверяют полезной
нагрузке события. Операции принимают ES-клиент явно (по умолчанию
``app.elasticsearch.es_client``), поэтому в тестах подставляется клиент
Testcontainer'а.
"""

from __future__ import annotations

import uuid

from elasticsearch import AsyncElasticsearch, NotFoundError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.elasticsearch import CATALOG_INDEX, delete_index, ensure_index
from app.models.catalog import Product

#: Размер пачки для keyset-сканирования при полном реиндексе.
BULK_BATCH = 500


def product_document(product: Product, category_name: str) -> dict:
    """Строит ES-документ по строке продукта (соответствует mapping D5).

    ``price`` приводится к ``float`` (mapping ``scaled_float`` с масштабом 100);
    даты — epoch-миллисекунды; ``attributes`` — ``dict`` (mapping ``flattened``).
    """
    return {
        "id": str(product.id),
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "category_id": str(product.category_id),
        "category_name": category_name,
        "price": float(product.price),
        "currency": product.currency,
        "attributes": product.attributes or {},
        "is_active": bool(product.is_active),
        "created_at": int(product.created_at.timestamp() * 1000),
        "updated_at": int(product.updated_at.timestamp() * 1000),
    }


async def index_product(
    client: AsyncElasticsearch, product: Product, category_name: str
) -> None:
    """Индексирует/переиндексирует продукт по id (идемпотентно)."""
    await client.index(
        index=CATALOG_INDEX,
        id=str(product.id),
        document=product_document(product, category_name),
    )


async def delete_product(client: AsyncElasticsearch, product_id: uuid.UUID) -> None:
    """Удаляет документ продукта из индекса; ``404`` игнорируется."""
    try:
        await client.delete(index=CATALOG_INDEX, id=str(product_id))
    except NotFoundError:
        pass


async def _scan_products(
    db: AsyncSession, after_id: uuid.UUID | None = None
) -> list[Product]:
    """Читает пачку продуктов keyset-ом (без ``search_after``) с категорией."""
    stmt = (
        select(Product)
        .options(joinedload(Product.category))
        .order_by(Product.id)
        .limit(BULK_BATCH)
    )
    if after_id is not None:
        stmt = stmt.where(Product.id > after_id)
    return list((await db.execute(stmt)).scalars())


async def reindex_all(client: AsyncElasticsearch, db: AsyncSession) -> int:
    """Перестраивает индекс целиком из PostgreSQL (пакетно + bulk).

    Сначала удаляет индекс (сходимость к текущему состоянию БД: стухшие
    документы исчезают), затем создаёт заново с mapping по D5 и переиндексирует
    все продукты пачками.

    Возвращает:
        Число проиндексированных продуктов.

    Исключения:
        RuntimeError: если bulk-операция вернула ошибки на уровне элементов.
    """
    await delete_index(client)
    await ensure_index(client)
    count = 0
    last_id = None
    while True:
        products = await _scan_products(db, after_id=last_id)
        if not products:
            break
        operations: list[dict] = []
        for product in products:
            operations.append(
                {"index": {"_index": CATALOG_INDEX, "_id": str(product.id)}}
            )
            operations.append(product_document(product, product.category.name))
        response = await client.bulk(operations=operations)
        if response.get("errors"):
            raise RuntimeError("bulk indexing returned errors; reindex aborted")
        count += len(products)
        last_id = products[-1].id
    await client.indices.refresh(index=CATALOG_INDEX)
    return count
