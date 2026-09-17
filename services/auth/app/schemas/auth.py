"""Pydantic-схемы запросов и ответов auth-сервиса.

Задают валидацию на границе API (``EmailStr``, минимальная длина пароля)
и структуру ответов, в том числе пары токенов.
"""
from pydantic import BaseModel, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Запрос регистрации.

    Атрибуты:
        email: Email пользователя.
        password: Пароль (минимум 8 символов).
    """
    email: EmailStr
    password: str = Field(..., min_length=8)

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

    class Config:
        from_attributes = True

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
