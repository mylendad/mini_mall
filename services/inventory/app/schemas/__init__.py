"""Pydantic-схемы инвентаря (запросы/ответы API)."""

from app.schemas.inventory import (
    AvailabilityBatchItem,
    AvailabilityBatchRequest,
    AvailabilityBatchResponse,
    AvailabilityResponse,
    ReservationCreate,
    ReservationResponse,
    StockItemAdjust,
    StockItemCreate,
    StockItemListResponse,
    StockItemResponse,
    StockItemThresholdUpdate,
)

__all__ = [
    "AvailabilityBatchItem",
    "AvailabilityBatchRequest",
    "AvailabilityBatchResponse",
    "AvailabilityResponse",
    "ReservationCreate",
    "ReservationResponse",
    "StockItemAdjust",
    "StockItemCreate",
    "StockItemListResponse",
    "StockItemResponse",
    "StockItemThresholdUpdate",
]
