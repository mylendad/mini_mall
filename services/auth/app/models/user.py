"""SQLAlchemy-модели: пользователи и refresh-токены.

База данных сервиса изолирована (``mini_mall_auth``); таблицы создаются
миграциями Alembic (``alembic/versions/0001_initial.py``).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """Модель пользователя.

    Атрибуты:
        id: UUID пользователя.
        email: Email (уникальный, индексированный).
        password_hash: Хэш пароля (bcrypt, ``$2b$...``).
        roles: Список ролей (JSON).
        is_active: Активна ли учётная запись.
        created_at: Время создания (UTC).
        updated_at: Время последнего обновления (UTC).
        refresh_tokens: Связанные refresh-токены (каскадное удаление).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=["customer"])
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """Модель refresh-токена (в БД хранится только хэш).

    Атрибуты:
        id: UUID токена.
        user_id: Владелец (удаляется каскадом вместе с пользователем).
        token_hash: SHA-256 хэш непрозрачного токена (уникальный).
        expires_at: Момент истечения (UTC).
        is_revoked: Признак отзыва (ротация, логаут, reuse detection).
        created_at: Время создания (UTC).
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")
