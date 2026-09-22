"""Генерация непрозрачных refresh-токенов и их хэширование.

Токены криптостойкие (``secrets.token_urlsafe``); в базу сохраняется только
SHA-256 хэш, поэтому даже при утечке БД токен использовать нельзя.
"""

import hashlib
import secrets


def generate_opaque_token() -> tuple[str, str]:
    """Генерирует непрозрачный refresh-токен.

    Возвращает:
        Кортеж ``(токен, sha256-хэш)``. Клиенту выдаётся токен, в БД
        сохраняется хэш.
    """
    token = secrets.token_urlsafe(64)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


def hash_token(token: str) -> str:
    """Вычисляет SHA-256 хэш токена для поиска и хранения.

    Параметры:
        token: Токен, полученный от клиента.

    Возвращает:
        Hex-строку хэша (64 символа).
    """
    return hashlib.sha256(token.encode()).hexdigest()
