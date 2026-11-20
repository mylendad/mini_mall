"""Репозиторий резервов: атомарные условные UPDATE без перепродажи.

Все операции изменения состояния — один SQL-запрос с условием в WHERE
(минимальное окно блокировки; перепродажа невозможна по построению).
Коммит — во владении сервисного слоя; ``flush`` выполняется здесь.
"""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Reservation, StockItem


class ReservationRepository:
    """Работа с моделями :class:`Reservation` и :class:`StockItem`.

    Параметры:
        db: Асинхронная сессия SQLAlchemy (обычно из ``Depends(get_db)``).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, reservation_id: uuid.UUID) -> Reservation | None:
        """Возвращает резерв по UUID или ``None``."""
        result = await self.db.execute(
            select(Reservation).where(Reservation.id == reservation_id)
        )
        return result.scalars().first()

    async def get_by_idempotency_key(self, key: str) -> Reservation | None:
        """Возвращает резерв по ключу идемпотентности или ``None``."""
        result = await self.db.execute(
            select(Reservation).where(Reservation.idempotency_key == key)
        )
        return result.scalars().first()

    async def get_by_holder_and_sku(
        self, holder_ref: str, sku: str
    ) -> Reservation | None:
        """Возвращает резерв владельца по SKU (любой статус) или ``None``.

        Используется обработчиком команд саги: ``holder_ref`` — id заказа,
        ``sku`` берётся из присоединённой складской позиции.
        """
        result = await self.db.execute(
            select(Reservation)
            .join(StockItem, Reservation.stock_item_id == StockItem.id)
            .where(Reservation.holder_ref == holder_ref, StockItem.sku == sku)
            .order_by(Reservation.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def reserve(
        self,
        *,
        stock_item_id: uuid.UUID,
        quantity: int,
        holder_ref: str | None,
        idempotency_key: str | None,
        expires_at: datetime,
    ) -> Reservation | None:
        """Создаёт резерв одним атомарным условным UPDATE.

        ``SET quantity_reserved = quantity_reserved + :q
        WHERE id = :id AND quantity_on_hand - quantity_reserved >= :q`` —
        ноль совпавших строк означает нехватку склада (``None``). Строка
        резерва вставляется в той же транзакции. ``flush`` без commit.
        """
        result = await self.db.execute(
            update(StockItem)
            .where(
                StockItem.id == stock_item_id,
                StockItem.quantity_on_hand - StockItem.quantity_reserved >= quantity,
            )
            .values(quantity_reserved=StockItem.quantity_reserved + quantity)
            .returning(StockItem.id)
        )
        if result.first() is None:
            return None
        reservation = Reservation(
            stock_item_id=stock_item_id,
            quantity=quantity,
            status="active",
            holder_ref=holder_ref,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
        )
        self.db.add(reservation)
        await self.db.flush()
        return reservation

    async def confirm(self, reservation: Reservation) -> Reservation | None:
        """Подтверждает резерв одним атомарным условным UPDATE.

        Списывает ``quantity`` из ``quantity_on_hand`` и ``quantity_reserved``
        только если резерв ещё ``active`` и обе величины >= quantity.
        Ноль совпавших строк -> ``None`` (уже подтверждён/освобождён/истёк —
        решает вызывающий код по статусу). ``flush`` без commit.
        """
        result = await self.db.execute(
            update(StockItem)
            .where(
                StockItem.id == reservation.stock_item_id,
                StockItem.quantity_on_hand >= reservation.quantity,
                StockItem.quantity_reserved >= reservation.quantity,
            )
            .values(
                quantity_on_hand=StockItem.quantity_on_hand - reservation.quantity,
                quantity_reserved=StockItem.quantity_reserved - reservation.quantity,
            )
            .returning(StockItem.id)
        )
        if result.first() is None:
            return None
        await self.db.execute(
            update(Reservation)
            .where(Reservation.id == reservation.id)
            .values(status="confirmed")
        )
        reservation.status = "confirmed"
        await self.db.refresh(reservation)
        return reservation

    async def release(self, reservation: Reservation) -> Reservation | None:
        """Освобождает резерв одним атомарным условным UPDATE.

        Возвращает ``quantity`` из ``quantity_reserved`` только если резерв
        ещё ``active``. Ноль совпавших строк -> ``None``. ``flush`` без commit.
        """
        result = await self.db.execute(
            update(StockItem)
            .where(
                StockItem.id == reservation.stock_item_id,
                StockItem.quantity_reserved >= reservation.quantity,
            )
            .values(
                quantity_reserved=StockItem.quantity_reserved - reservation.quantity
            )
            .returning(StockItem.id)
        )
        if result.first() is None:
            return None
        await self.db.execute(
            update(Reservation)
            .where(Reservation.id == reservation.id)
            .values(status="released")
        )
        reservation.status = "released"
        await self.db.refresh(reservation)
        return reservation

    async def expire(self, reservation: Reservation) -> Reservation | None:
        """Переводит резерв в ``expired`` с возвратом склада (``flush`` без commit).

        Используется заданием истечения: резерв уже выбран ``FOR UPDATE
        SKIP LOCKED``, поэтому условие статуса защищает от гонки с
        конкурентным confirm/release.
        """
        result = await self.db.execute(
            update(StockItem)
            .where(
                StockItem.id == reservation.stock_item_id,
                StockItem.quantity_reserved >= reservation.quantity,
            )
            .values(
                quantity_reserved=StockItem.quantity_reserved - reservation.quantity
            )
            .returning(StockItem.id)
        )
        if result.first() is None:
            return None
        await self.db.execute(
            update(Reservation)
            .where(Reservation.id == reservation.id)
            .values(status="expired")
        )
        reservation.status = "expired"
        await self.db.refresh(reservation)
        return reservation

    async def select_expired(
        self, *, now: datetime, limit: int
    ) -> list[Reservation]:
        """Выбирает ``active`` резервы с ``expires_at < now`` ``FOR UPDATE SKIP LOCKED``.

        Резерв, который конкурентная транзакция прямо сейчас подтверждает,
        пропускается в этом проходе (SKIP LOCKED) — не портится и не
        блокируется.
        """
        result = await self.db.execute(
            select(Reservation)
            .where(Reservation.status == "active", Reservation.expires_at < now)
            .order_by(Reservation.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())
