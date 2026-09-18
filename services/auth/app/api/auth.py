"""HTTP-эндпоинты аутентификации: регистрация, логин, ротация токенов.

Маршруты регистрируются с префиксом ``/api/v1``:
``POST /auth/register``, ``POST /auth/login``, ``POST /auth/refresh``,
``POST /auth/logout``, ``GET /users/me``.
"""
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.database import get_db
from app.errors import error_detail
from app.repositories.auth_repo import AuthRepository
from app.schemas.auth import (
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.services.token import generate_opaque_token, hash_token
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1")

@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Регистрирует нового пользователя.

    Хэширует пароль (bcrypt) и создаёт запись в ``users``. При дублирующем
    email возвращает ``409 DUPLICATE_EMAIL``.

    Параметры:
        payload: Email и пароль (минимум 8 символов).
        db: Сессия базы данных (из ``Depends``).

    Возвращает:
        Профиль созданного пользователя (без пароля).
    """
    repo = AuthRepository(db)
    existing = await repo.get_user_by_email(payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("DUPLICATE_EMAIL", "Email already registered")
        )
    hashed = hash_password(payload.password)
    user = await repo.create_user(email=payload.email, password_hash=hashed, roles=["customer"])
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("DUPLICATE_EMAIL", "Email already registered")
        )
    return UserResponse(id=str(user.id), email=user.email, roles=user.roles)

@router.post("/auth/login", response_model=TokenResponse)
async def login(payload: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """Аутентифицирует пользователя и выдаёт пару токенов.

    Проверяет пароль и активность учётной записи. При неверных учётных данных
    возвращает ``401 INVALID_CREDENTIALS``.

    Возвращает:
        JWT access-токен и непрозрачный refresh-токен.
    """
    repo = AuthRepository(db)
    user = await repo.get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user.password_hash) or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("INVALID_CREDENTIALS", "Invalid email, password, or inactive user")
        )

    access_token = create_access_token(user.id, user.roles)
    plain_refresh, ref_hash = generate_opaque_token()
    await repo.create_refresh_token(user.id, ref_hash)
    await db.commit()

    return TokenResponse(access_token=access_token, refresh_token=plain_refresh)

@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh_tokens(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Выполняет конкуренто-безопасную ротацию refresh-токена.

    Читает токен строкой ``SELECT ... FOR UPDATE``, поэтому при двух
    одновременных запросах с одним токеном успешен только один (второй
    получает ``401``). Если обнаружено повторное использование уже отозванного
    токена, отзывает все refresh-токены пользователя (reuse detection).

    Возвращает:
        Новую пару токенов.

    Исключения:
        HTTPException(401): токен не найден, истёк, отозван или
            владелец неактивен.
    """
    repo = AuthRepository(db)
    ref_hash = hash_token(payload.refresh_token)

    async with db.begin():
        token_obj = await repo.get_refresh_token_for_update(ref_hash)
        if not token_obj:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error_detail("INVALID_REFRESH_TOKEN", "Refresh token not found")
            )

        # Token Reuse Detection
        if token_obj.is_revoked:
            await repo.revoke_all_user_tokens(token_obj.user_id)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error_detail("TOKEN_REUSE_DETECTED", "Revoked token reuse detected. All tokens revoked.")
            )

        # Expiration check
        if token_obj.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
            token_obj.is_revoked = True
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error_detail("EXPIRED_REFRESH_TOKEN", "Refresh token expired")
            )

        user = await repo.get_user_by_id(token_obj.user_id)
        if not user or not user.is_active:
            token_obj.is_revoked = True
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error_detail("INACTIVE_USER", "User is inactive or not found")
            )

        # Rotate
        token_obj.is_revoked = True
        plain_new, new_hash = generate_opaque_token()
        await repo.create_refresh_token(user.id, new_hash)
        new_access = create_access_token(user.id, user.roles)

    return TokenResponse(access_token=new_access, refresh_token=plain_new)

@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest, db: AsyncSession = Depends(get_db)):
    """Отзывает refresh-токен (идемпотентно).

    Повторный вызов с тем же токеном снова возвращает ``204``; после
    отзыва ``POST /auth/refresh`` с этим токеном вернёт ``401``.
    """
    repo = AuthRepository(db)
    ref_hash = hash_token(payload.refresh_token)
    await repo.revoke_token_by_hash(ref_hash)
    await db.commit()

@dataclass
class TrustedUser:
    """Идентичность, переданная API Gateway в доверенных заголовках.

    Атрибуты:
        user_id: UUID пользователя (из ``X-User-ID``).
        roles: Роли пользователя (из ``X-User-Roles``).
    """
    user_id: uuid.UUID
    roles: list[str]


def get_trusted_user(
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    x_user_roles: str | None = Header(default=None, alias="X-User-Roles"),
) -> TrustedUser:
    """Извлекает идентичность из доверенных заголовков API Gateway.

    Заголовки ``X-User-ID`` и ``X-User-Roles`` инжектирует API Gateway после
    аутентификации. При их отсутствии или некорректном формате возвращается
    ``401``.

    Параметры:
        x_user_id: UUID пользователя.
        x_user_roles: Роли через запятую.

    Возвращает:
        Идентичность :class:`TrustedUser`.

    Исключения:
        HTTPException(401): заголовки отсутствуют или ``X-User-ID`` не UUID.
    """
    if not x_user_id or not x_user_roles:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("MISSING_USER_CONTEXT", "X-User-ID and X-User-Roles headers are required"),
        )
    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("INVALID_USER_CONTEXT", "X-User-ID header must contain a valid UUID"),
        )
    roles = [role.strip() for role in x_user_roles.split(",") if role.strip()]
    return TrustedUser(user_id=user_id, roles=roles)


@router.get("/users/me", response_model=UserResponse)
async def get_current_user_profile(user: TrustedUser = Depends(get_trusted_user), db: AsyncSession = Depends(get_db)):
    """Возвращает профиль авторизованного пользователя.

    Идентичность берётся из доверенных заголовков ``X-User-ID``/``X-User-Roles``,
    инжектируемых API Gateway; email подтягивается из базы данных. Профиль
    неактивного или несуществующего пользователя недоступен (``401``).

    Параметры:
        user: Идентичность из доверенных заголовков.
        db: Сессия базы данных.

    Возвращает:
        Профиль пользователя (без пароля).
    """
    repo = AuthRepository(db)
    db_user = await repo.get_user_by_id(user.user_id)
    if not db_user or not db_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=error_detail("USER_NOT_FOUND", "User not found or inactive"))

    return UserResponse(id=str(db_user.id), email=db_user.email, roles=user.roles)
