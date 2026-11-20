"""HTTP-эндпоинты резервов.

Маршруты: создание (``POST /reservations``, поддержка ``Idempotency-Key``),
подтверждение (``POST /reservations/{id}/confirm``), освобождение
(``POST /reservations/{id}/release``), чтение (``GET /reservations/{id}``).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas.inventory import ReservationCreate, ReservationResponse
from app.services.reservations import ReservationService

router = APIRouter(prefix="/reservations", tags=["reservations"])


def _correlation_from_request_id(request_id: str | None) -> uuid.UUID | None:
    """Извлекает ``correlation_id`` из ``X-Request-ID`` (если это UUID)."""
    if not request_id:
        return None
    try:
        return uuid.UUID(request_id)
    except ValueError:
        return None


@router.post("", response_model=ReservationResponse, status_code=201)
async def create_reservation(
    payload: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> ReservationResponse:
    """Создаёт резерв (``201``); ``(409)`` нехватка склада, ``(404)`` SKU.

    Заголовок ``Idempotency-Key`` сохраняется как ключ идемпотентности:
    повтор с тем же ключом возвращает исходный резерв без второго резерва.
    """
    reservation = await ReservationService(
        db, settings.reservation_default_ttl_seconds
    ).reserve(
        sku=payload.sku,
        quantity=payload.quantity,
        holder_ref=payload.holder_ref,
        ttl_seconds=payload.ttl_seconds,
        idempotency_key=idempotency_key,
        correlation_id=_correlation_from_request_id(x_request_id),
    )
    return ReservationResponse.model_validate(reservation)


@router.post("/{reservation_id}/confirm", response_model=ReservationResponse)
async def confirm_reservation(
    reservation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    x_request_id: str | None = Header(default=None),
) -> ReservationResponse:
    """Подтверждает резерв (``200``); ``(404)``, ``(409)`` не active/склад."""
    reservation = await ReservationService(
        db, settings.reservation_default_ttl_seconds
    ).confirm(
        reservation_id, correlation_id=_correlation_from_request_id(x_request_id)
    )
    return ReservationResponse.model_validate(reservation)


@router.post("/{reservation_id}/release", response_model=ReservationResponse)
async def release_reservation(
    reservation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    x_request_id: str | None = Header(default=None),
) -> ReservationResponse:
    """Освобождает резерв (``200``); ``(404)``, ``(409)`` не active."""
    reservation = await ReservationService(
        db, settings.reservation_default_ttl_seconds
    ).release(
        reservation_id, correlation_id=_correlation_from_request_id(x_request_id)
    )
    return ReservationResponse.model_validate(reservation)


@router.get("/{reservation_id}", response_model=ReservationResponse)
async def get_reservation(
    reservation_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ReservationResponse:
    """Возвращает резерв (``200``) или ``404 RESERVATION_NOT_FOUND``."""
    reservation = await ReservationService(
        db, settings.reservation_default_ttl_seconds
    ).get(reservation_id)
    return ReservationResponse.model_validate(reservation)
