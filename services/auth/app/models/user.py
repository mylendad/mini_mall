"""SQLAlchemy-модели: пользователи и refresh-токены.

База данных сервиса изолирована (``mini_mall_auth``); таблицы создаются
миграциями Alembic (``alembic/versions/0001_initial.py``).
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    roles = Column(JSON, nullable=False, default=["customer"])
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")

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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    user = relationship("User", back_populates="refresh_tokens")
