"""Юнит-тесты логики безопасности: хэширование паролей, JWT и токены.

Проверяют генерацию/проверку bcrypt-хэшей, JWT access-токенов (TTL, подпись)
и непрозрачных refresh-токенов. Не требуют базы данных.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import settings
from app.services.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.services.token import generate_opaque_token, hash_token


def test_hash_password_and_verify():
    hashed = hash_password("securepassword123")
    assert hashed.startswith("$2b$")
    assert verify_password("securepassword123", hashed)
    assert not verify_password("wrong-password", hashed)


def test_hash_password_uses_unique_salt():
    assert hash_password("same-password") != hash_password("same-password")


def test_create_and_decode_access_token():
    user_id = uuid.uuid4()
    token = create_access_token(user_id, ["customer"])
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    assert payload["sub"] == str(user_id)
    assert payload["roles"] == ["customer"]
    assert {"exp", "iat", "jti"}.issubset(payload)

    iat = datetime.fromtimestamp(payload["iat"], tz=UTC)
    exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
    expected = settings.access_token_expire_minutes * 60
    assert (exp - iat).total_seconds() == pytest.approx(expected, abs=1)


def test_decode_rejects_expired_token():
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "exp": now - timedelta(minutes=1),
            "iat": now - timedelta(minutes=10),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(expired, settings.jwt_secret, algorithms=["HS256"])


def test_decode_rejects_wrong_secret():
    token = create_access_token(uuid.uuid4(), ["customer"])
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            token, "wrong-secret-that-is-long-enough-123456789", algorithms=["HS256"]
        )


def test_generate_opaque_token_unique_and_hashed():
    token_a, hash_a = generate_opaque_token()
    token_b, hash_b = generate_opaque_token()
    assert token_a != token_b
    assert len(token_a) > 64
    assert hash_a == hash_token(token_a)
    assert hash_b == hash_token(token_b)
    assert hash_a != hash_b
    assert len(hash_a) == 64
