"""Pydantic-схемы запросов и ответов auth-сервиса.

Задают валидацию на границе API (``EmailStr``, минимальная длина пароля)
и структуру ответов, в том числе пары токенов.
"""

import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegisterRequest(BaseModel):
    """Запрос регистрации.

    Атрибуты:
        email: Email пользователя.
        password: Пароль (минимум 8 символов).
    """

    email: EmailStr
    password: str = Field(..., min_length=8)

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        """Проверяет пароль на соответствие политикам сложности.

        Пароль должен содержать символы разных регистров, цифры и спецсимволы.

        Параметры:
            v: Входящая строка с паролем.

        Возвращает:
            Оригинальную строку пароля при успешной валидации.

        Исключения:
            ValueError: Если пароль не удовлетворяет какому-либо из условий
                (сообщение исключения будет преобразовано FastAPI в 422 статус).
        """
        if not re.search(r"[A-Z]", v):
            raise ValueError("Пароль должен содержать хотя бы одну заглавную букву")

        if not re.search(r"[a-z]", v):
            raise ValueError("Пароль должен содержать хотя бы одну строчную букву")

        if not re.search(r"\d", v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")

        if not re.search(r"[@$!%*?&#]", v):
            raise ValueError(
                "Пароль должен содержать хотя бы один специальный символ (@$!%*?&#)"
            )

        return v


class UserResponse(BaseModel):
    """Профиль пользователя в ответах API (без пароля).

    Атрибуты:
        id: UUID пользователя (строка).
        email: Email пользователя.
        roles: Список ролей.
    """

    id: str
    email: EmailStr
    roles: list[str]

    model_config = ConfigDict(from_attributes=True)


class UserLoginRequest(BaseModel):
    """Запрос логина.

    Атрибуты:
        email: Email пользователя.
        password: Пароль.
    """

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Пара токенов, возвращаемая при логине и ротации.

    Атрибуты:
        access_token: JWT (HS256, 15 минут).
        refresh_token: Непрозрачный токен (7 суток).
        token_type: Тип токена (``bearer``).
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Запрос ротации: передаётся текущий refresh-токен.

    Атрибуты:
        refresh_token: Непрозрачный refresh-токен.
    """

    refresh_token: str


class LogoutRequest(BaseModel):
    """Запрос логаута.

    Атрибуты:
        refresh_token: Непрозрачный refresh-токен к отзыву.
    """

    refresh_token: str
