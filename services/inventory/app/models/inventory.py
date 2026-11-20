"""SQLAlchemy-модели инвентаря: склад, резервы, идемпотентность команд.

PostgreSQL — единственный источник истины инвентаря. Схема (таблицы,
ограничения, индексы) создаётся миграциями Alembic, никогда на старте
приложения. Доступная к резервированию величина производная:
``available = quantity_on_hand - quantity_reserved`` — никогда не хранится.
Инвариант ``quantity_reserved <= quantity_on_hand`` защищён CHECK-ограничением.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockItem(Base):
    """Модель складской позиции.

    Атрибуты:
        id: UUID позиции.
        catalog_product_id: Необязательная ссылка на продукт каталога
            (хранится как opaque reference; валидация — вне этого сервиса).
        sku: Уникальный артикул (индексировано).
        quantity_on_hand: Физическое количество (>= 0).
        quantity_reserved: Зарезервированное количество (>= 0).
        low_stock_threshold: Порог low-stock оповещения (>= 0, ``0`` — оповещения
            выключены).
        created_at: Время создания (UTC).
        updated_at: Время последнего обновления (UTC).
    """

    __tablename__ = "stock_items"
    __table_args__ = (
        CheckConstraint(
            "quantity_reserved <= quantity_on_hand",
            name="ck_stock_items_reserved_le_on_hand",
        ),
        CheckConstraint("quantity_on_hand >= 0", name="ck_stock_items_on_hand_nonneg"),
        CheckConstraint(
            "quantity_reserved >= 0", name="ck_stock_items_reserved_nonneg"
        ),
        CheckConstraint(
            "low_stock_threshold >= 0", name="ck_stock_items_threshold_nonneg"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    catalog_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    @property
    def available(self) -> int:
        """Производная доступная величина (``on_hand - reserved``)."""
        return self.quantity_on_hand - self.quantity_reserved


class Reservation(Base):
    """Модель резерва (жизненный цикл ``active`` → ``confirmed``/``released``/
    ``expired``).

    Атрибуты:
        id: UUID резерва.
        stock_item_id: Складская позиция (FK, RESTRICT).
        quantity: Зарезервированное количество (> 0).
        status: Состояние (``active``/``confirmed``/``released``/``expired``).
        holder_ref: Ссылка на владельца (например, id заказа или корзины).
        idempotency_key: Уникальный ключ идемпотентности (nullable).
        expires_at: Момент истечения активного резерва (UTC).
        created_at: Время создания (UTC).
        updated_at: Время последнего обновления (UTC).
    """

    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_reservations_quantity_positive"),
        CheckConstraint(
            r"status ~ '^(active|confirmed|released|expired)$'",
            name="ck_reservations_status_domain",
        ),
        Index(
            "ix_reservations_active_expires_at",
            "expires_at",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    stock_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stock_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    holder_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ProcessedCommand(Base):
    """Потреблённые команды саги (идемпотентность потребителя по ``event_id``).

    Атрибуты:
        event_id: UUID события-команды (PK).
        processed_at: Время обработки (UTC).
    """

    __tablename__ = "processed_commands"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
