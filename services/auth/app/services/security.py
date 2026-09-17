"""Утилиты безопасности: хэширование паролей и JWT-access-токены.

Пароли хэшируются напрямую через ``bcrypt`` (без passlib: современные версии
несовместимы с bcrypt 5.x). Access-токены — PyJWT (HS256) с claims
``sub``/``roles``/``exp``/``iat``/``jti``; PII в токены не попадает.
"""
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings


def hash_password(password: str) -> str:
    """Хэширует пароль через bcrypt с уникальной солью.

    Параметры:
        password: Пароль в открытом виде.

    Возвращает:
        Строку формата bcrypt ``$2b$...``.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль против сохранённого хэша.

    Параметры:
        plain_password: Проверяемый пароль.
        hashed_password: Хэш из базы данных.

    Возвращает:
        ``True`` при совпадении; ``False`` при несовпадении или неверном хэше.
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False

def create_access_token(user_id: uuid.UUID, roles: list[str]) -> str:
    """Создаёт JWT access-токен (HS256).

    Параметры:
        user_id: Идентификатор пользователя (попадает в claim ``sub``).
        roles: Роли пользователя (claim ``roles``).

    Возвращает:
        Закодированный JWT с claims ``sub``, ``roles``, ``exp``, ``iat``, ``jti``.
    """
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "roles": roles,
        "exp": expire,
        "iat": now,
        "jti": str(uuid.uuid4())
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def decode_access_token(token: str) -> dict:
    """Проверяет подпись и декодирует JWT.

    Параметры:
        token: JWT-строка.

    Возвращает:
        Словарь claims.

    Исключения:
        jwt.PyJWTError: при истёкшем, неверно подписанном или мусорном токене.
    """
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])