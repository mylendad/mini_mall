"""Redis-хранилище корзин (задача 3.1, design D1/D2).

Раскладка данных:
    - ключ ``cart:{user_id}`` — Hash: field = ``product_id`` (UUID),
      value = JSON ``{"quantity": int, "added_at": ISO-8601 UTC}``;
    - TTL ключа обновляется при каждой записи (volatile-состояние);
    - лимит различных товаров и инкремент количества выполняются в одном
      Lua-скрипте: два конкурентных добавления одного товара дают
      количество 2 без дублей, а частичных мутаций не бывает (скрипт либо
      целиком применяется, либо целиком отклонён).

Недоступность Redis (``RedisError``/``OSError``) пробрасывается как
:class:`CartStorageUnavailable` (-> контролируемый 503), не искажая
корзину. Отсутствующий ключ читается как пустая корзина (TTL-выселение —
нормальное поведение, сценарий «Cart expiry is volatile by design»).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from redis.exceptions import RedisError

from app.application.protocols import CartItemNotFound, CartStorageUnavailable
from app.config import settings
from app.domain.cart import (
    Cart,
    CartItem,
    CartLimitExceeded,
    QuantityOutOfBounds,
)

logger = structlog.get_logger()

CART_KEY_PREFIX = "cart"

#: Коды возврата Lua-скриптов (0 — успех; -1 лимит; -2 границы количества).
_OK = 0
_LIMIT = -1
_BOUNDS = -2

_ADD_SCRIPT = """
local exists = redis.call('HEXISTS', KEYS[1], ARGV[1])
local quantity = tonumber(ARGV[2])
local max_quantity = tonumber(ARGV[3])
local max_items = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
if exists == 1 then
  local value = cjson.decode(redis.call('HGET', KEYS[1], ARGV[1]))
  local new_quantity = value.quantity + quantity
  if new_quantity > max_quantity then return -2 end
  value.quantity = new_quantity
  redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(value))
else
  if redis.call('HLEN', KEYS[1]) >= max_items then return -1 end
  redis.call('HSET', KEYS[1], ARGV[1], ARGV[6])
end
redis.call('EXPIRE', KEYS[1], ttl)
return 0
"""

_SET_SCRIPT = """
if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 0 then return -1 end
local value = cjson.decode(redis.call('HGET', KEYS[1], ARGV[1]))
value.quantity = tonumber(ARGV[2])
redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(value))
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 0
"""

_REMOVE_SCRIPT = """
if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 0 then return -1 end
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 0
"""


def cart_key(user_id: UUID) -> str:
    """Ключ корзины пользователя: ``cart:{user_id}``."""
    return f"{CART_KEY_PREFIX}:{user_id}"


def _encode_item(item: CartItem) -> str:
    """JSON-значение поля Hash: ``{"quantity", "added_at"}``."""
    return json.dumps(
        {
            "quantity": item.quantity,
            "added_at": item.added_at.isoformat(),
        }
    )


def _decode_item(product_id: UUID, raw: Any) -> CartItem:
    """Обратное преобразование JSON-значения поля в :class:`CartItem`."""
    data = json.loads(raw)
    return CartItem(
        product_id=product_id,
        quantity=int(data["quantity"]),
        added_at=datetime.fromisoformat(data["added_at"]),
    )


class RedisCartRepository:
    """Реализация :class:`app.application.protocols.CartRepository` на Redis."""

    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client
        self._add_script = self._client.register_script(_ADD_SCRIPT)
        self._set_script = self._client.register_script(_SET_SCRIPT)
        self._remove_script = self._client.register_script(_REMOVE_SCRIPT)

    def _wrap(self, exc: Exception) -> CartStorageUnavailable:
        """Оборачивает сбой Redis в контролируемую ошибку (503)."""
        logger.error("cart_storage_unavailable", error=str(exc))
        return CartStorageUnavailable("cart storage is temporarily unavailable")

    async def get(self, user_id: UUID) -> Cart:
        """Читает корзину; отсутствие ключа — пустая корзина (TTL-выселение)."""
        try:
            raw = await self._client.hgetall(cart_key(user_id))
        except (RedisError, OSError) as exc:
            raise self._wrap(exc) from exc
        items = {}
        for field_value, raw_item in raw.items():
            product_id = UUID(field_value.decode() if isinstance(field_value, bytes) else field_value)
            items[product_id] = _decode_item(product_id, raw_item)
        return Cart(user_id=user_id, items=items)

    async def add_item(self, user_id: UUID, product_id: UUID, quantity: int) -> Cart:
        """Атомарное добавление: инкремент существующего либо новая строка.

        Лимит различных товаров (409) и границы количества (422) проверяются
        внутри того же атомарного юнита, что и запись + EXPIRE.
        """
        new_item = CartItem(
            product_id=product_id,
            quantity=quantity,
            added_at=datetime.now(UTC),
        )
        try:
            result = await self._add_script(
                keys=[cart_key(user_id)],
                args=[
                    str(product_id),
                    quantity,
                    settings.max_quantity,
                    settings.max_distinct_items,
                    settings.cart_ttl_seconds,
                    _encode_item(new_item),
                ],
            )
        except (RedisError, OSError) as exc:
            raise self._wrap(exc) from exc
        code = int(result)
        if code == _LIMIT:
            raise CartLimitExceeded("cart already holds the maximum number of distinct items")
        if code == _BOUNDS:
            raise QuantityOutOfBounds(
                f"quantity must be between 1 and {settings.max_quantity}"
            )
        return await self.get(user_id)

    async def set_quantity(
        self, user_id: UUID, product_id: UUID, quantity: int
    ) -> Cart:
        """Атомарная установка абсолютного количества; отсутствие -> 404."""
        try:
            result = await self._set_script(
                keys=[cart_key(user_id)],
                args=[str(product_id), quantity, settings.cart_ttl_seconds],
            )
        except (RedisError, OSError) as exc:
            raise self._wrap(exc) from exc
        if int(result) != _OK:
            raise CartItemNotFound(str(product_id))
        return await self.get(user_id)

    async def remove_item(self, user_id: UUID, product_id: UUID) -> Cart:
        """Атомарное удаление товара; отсутствие -> 404."""
        try:
            result = await self._remove_script(
                keys=[cart_key(user_id)],
                args=[str(product_id), settings.cart_ttl_seconds],
            )
        except (RedisError, OSError) as exc:
            raise self._wrap(exc) from exc
        if int(result) != _OK:
            raise CartItemNotFound(str(product_id))
        return await self.get(user_id)

    async def clear(self, user_id: UUID) -> Cart:
        """Удаляет ключ корзины целиком."""
        try:
            await self._client.delete(cart_key(user_id))
        except (RedisError, OSError) as exc:
            raise self._wrap(exc) from exc
        return Cart(user_id=user_id, items={})
