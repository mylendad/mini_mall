"""Сервис продуктов.

Владеет транзакционной границей и точкой синхронизации: после успешного
commit'а продуктовой записи в той же транзакции ставится событие в outbox
(``product.created``/``product.updated``/``product.deleted``) с толстым payload —
полным снимком продукта (Event-Carried State Transfer). Откат транзакции
не оставляет ни продукта, ни события.

Точечные чтения ``GET /products/{id}`` идут через Redis read-through кэш (D11)
с TTL; при обновлении/удалении ключ инвалидируется после commit. Любой сбой
Redis лишь деградирует путь чтения на PostgreSQL.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import cache
from app.errors import IntegrityErrorMapper, error_detail
from app.models.catalog import Product
from app.repositories.category_repo import CategoryRepository
from app.repositories.product_repo import ProductRepository
from app.schemas.catalog import ProductCreate, ProductResponse, ProductUpdate
from app.services.sync import (
    PRODUCT_CREATED,
    PRODUCT_DELETED,
    PRODUCT_UPDATED,
    build_envelope,
    enqueue_event,
)

LIST_SORT_KEYS = {"created_at", "updated_at", "name", "price"}


class ProductsService:
    """Операции с продуктами.

    Параметры:
        db: Асинхронная сессия SQLAlchemy.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ProductRepository(db)
        self.mapper = IntegrityErrorMapper()

    async def _category_exists(self, category_id: uuid.UUID) -> bool:
        """Проверяет существование категории (без загрузки продукта)."""
        return await CategoryRepository(self.db).get_by_id(category_id) is not None

    async def create(self, payload: ProductCreate) -> Product:
        """Создаёт продукт.

        Исключения:
            HTTPException(422): несуществующая категория (``INVALID_CATEGORY``).
            HTTPException(409): дубликат SKU (``DUPLICATE_SKU``).
        """
        if not await self._category_exists(payload.category_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=error_detail("INVALID_CATEGORY", "Category does not exist"),
            )
        if await self.repo.get_by_sku(payload.sku):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail("DUPLICATE_SKU", "Product SKU already exists"),
            )
        try:
            product = await self.repo.create(
                category_id=payload.category_id,
                name=payload.name,
                description=payload.description,
                price=payload.price,
                currency=payload.currency,
                sku=payload.sku,
                attributes=payload.attributes,
                is_active=payload.is_active,
            )
            await enqueue_event(self.db, build_envelope(PRODUCT_CREATED, product))
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            mapped = self.mapper.product_write(exc)
            if mapped is not None:
                raise HTTPException(
                    status_code=422
                    if mapped["code"] == "INVALID_CATEGORY"
                    else status.HTTP_409_CONFLICT,
                    detail=mapped,
                )
            raise
        return product

    async def get(self, product_id: uuid.UUID) -> Product:
        """Возвращает продукт (ORM) или ``404 PRODUCT_NOT_FOUND``.

        Используется внутренне (update/delete); для публичного чтения
        используйте :meth:`get_product` с read-through кэшем.
        """
        product = await self.repo.get_by_id(product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("PRODUCT_NOT_FOUND", "Product not found"),
            )
        return product

    async def get_product(self, product_id: uuid.UUID) -> dict:
        """Возвращает продукт через Redis read-through кэш (D11).

        Ключ ``catalog:product:{id}`` с TTL. При промахе — чтение из PostgreSQL
        и запись в кэш; при сбое Redis — деградация на прямое чтение из БД.
        Возвращает сериализованный ``ProductResponse``.
        """
        cached = await cache.get_product(product_id)
        if cached is not None:
            try:
                return json.loads(cached)
            except (TypeError, ValueError):
                await cache.delete_product(product_id)
        product = await self.repo.get_by_id(product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("PRODUCT_NOT_FOUND", "Product not found"),
            )
        payload = ProductResponse.model_validate(product).model_dump(mode="json")
        await cache.set_product(product_id, json.dumps(payload))
        return payload

    async def list(
        self,
        *,
        category_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        sort: str = "created_at",
        order: str = "desc",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Product], int]:
        """Возвращает ``(страница, всего)``; неверный ``sort`` -> ``422 INVALID_SORT``."""
        if sort not in LIST_SORT_KEYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=error_detail("INVALID_SORT", f"Unsupported sort key: {sort}"),
            )
        try:
            return await self.repo.list(
                category_id=category_id,
                is_active=is_active,
                sort=sort,
                order=order,
                offset=offset,
                limit=limit,
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=error_detail("INVALID_SORT", f"Unsupported sort key: {sort}"),
            )

    async def update(self, product_id: uuid.UUID, payload: ProductUpdate) -> Product:
        """Обновляет продукт и ставит ``product.updated`` в outbox.

        Исключения:
            HTTPException(404): продукт не найден.
            HTTPException(409): дубликат SKU.
            HTTPException(422): несуществующая категория.
        """
        product = await self.get(product_id)

        if payload.sku is not None and payload.sku != product.sku:
            existing = await self.repo.get_by_sku(payload.sku)
            if existing is not None and existing.id != product.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=error_detail("DUPLICATE_SKU", "Product SKU already exists"),
                )

        changes: dict[str, Any] = {}
        if (
            payload.category_id is not None
            and payload.category_id != product.category_id
        ):
            if not await self._category_exists(payload.category_id):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=error_detail("INVALID_CATEGORY", "Category does not exist"),
                )
            changes["category_id"] = payload.category_id
        for field in (
            "name",
            "description",
            "price",
            "currency",
            "sku",
            "attributes",
            "is_active",
        ):
            value = getattr(payload, field)
            if value is not None:
                changes[field] = value

        try:
            product = await self.repo.update(product, **changes)
            await enqueue_event(self.db, build_envelope(PRODUCT_UPDATED, product))
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            mapped = self.mapper.product_write(exc)
            if mapped is not None:
                raise HTTPException(
                    status_code=422
                    if mapped["code"] == "INVALID_CATEGORY"
                    else status.HTTP_409_CONFLICT,
                    detail=mapped,
                )
            raise
        await cache.delete_product(product_id)
        return product

    async def delete(self, product_id: uuid.UUID) -> None:
        """Удаляет продукт и ставит ``product.deleted`` в outbox."""
        product = await self.get(product_id)
        await self.repo.delete(product)
        await enqueue_event(self.db, build_envelope(PRODUCT_DELETED, product))
        await self.db.commit()
        await cache.delete_product(product_id)
