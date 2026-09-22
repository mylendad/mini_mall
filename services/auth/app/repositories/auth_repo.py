"""Репозиторий доступа к данным ``users`` и ``refresh_tokens``.

Описывает операции с моделями через переданную асинхронную сессию;
транзакционные границы (commit) управляются вызвающим кодом.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.models.user import RefreshToken, User


class AuthRepository:
    """Работа с моделями :class:`User` и :class:`RefreshToken`.

    Параметры:
        db: Асинхронная сессия SQLAlchemy (обычно из ``Depends(get_db)``).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_email(self, email: str) -> User | None:
        """Возвращает пользователя по email или ``None``."""
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalars().first()

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """Возвращает пользователя по UUID или ``None``."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalars().first()

    async def create_user(
        self, email: str, password_hash: str, roles: list[str] | None = None
    ) -> User:
        """Создаёт пользователя.

        Параметры:
            email: Email пользователя.
            password_hash: Хэш пароля (bcrypt).
            roles: Роли пользователя (по умолчанию ``["customer"]``).

        Возвращает:
            Новую модель :class:`User` (обновлённую из БД).
        """
        user = User(
            email=email, password_hash=password_hash, roles=roles or ["customer"]
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def create_refresh_token(
        self, user_id: uuid.UUID, token_hash: str
    ) -> RefreshToken:
        """Создаёт refresh-токен со сроком жизни из настроек.

        Параметры:
            user_id: Владелец токена.
            token_hash: SHA-256 хэш непрозрачного токена.

        Возвращает:
            Созданный :class:`RefreshToken`.
        """
        expires_at = datetime.now(UTC) + timedelta(
            days=settings.refresh_token_expire_days
        )
        refresh_token = RefreshToken(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )
        self.db.add(refresh_token)
        await self.db.flush()
        return refresh_token

    async def get_refresh_token_for_update(
        self, token_hash: str
    ) -> RefreshToken | None:
        """Читает refresh-токен с блокировкой ``FOR UPDATE``.

        Используется для конкуренто-безопасной ротации: между чтением и
        фиксацией строку не прочитает пере-запишет другой запрос.

        Параметры:
            token_hash: Хэш refresh-токена.

        Возвращает:
            :class:`RefreshToken` или ``None``.
        """
        result = await self.db.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update()
        )
        return result.scalars().first()

    async def revoke_all_user_tokens(self, user_id: uuid.UUID) -> None:
        """Отзывает все активные refresh-токены пользователя.

        Вызывается при обнаружении повторного использования отозванного токена.
        """
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked == False)
            .values(is_revoked=True)
        )

    async def revoke_token_by_hash(self, token_hash: str) -> bool:
        """Отзывает отдельный refresh-токен (идемпотентно).

        Параметры:
            token_hash: Хэш refresh-токена.

        Возвращает:
            ``True``, если токен существовал и был активен; иначе ``False``.
        """
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        token_obj = result.scalars().first()
        if token_obj and not token_obj.is_revoked:
            token_obj.is_revoked = True
            await self.db.flush()
            return True
        return False
