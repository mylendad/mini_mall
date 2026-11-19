"""Бизнес-метрики cart-сервиса (задача 6.3).

Технические (request'ы, latency) даёт ``common.observability``; здесь —
только бизнес-счётчики: добавления, удаления и отклонения валидации при
добавлении (не найден/неактивен/Catalog недоступен).
"""

from prometheus_client import Counter

#: Товары добавлены в корзину (успешные POST /cart/items).
cart_items_added_total = Counter(
    "cart_items_added_total",
    "Total number of items successfully added to carts",
)

#: Товары удалены из корзины (успешные DELETE /cart/items).
cart_items_removed_total = Counter(
    "cart_items_removed_total",
    "Total number of items removed from carts",
)

#: Отклонённые добавления: продукт не найден/неактивен/Catalog недоступен.
cart_validation_rejected_total = Counter(
    "cart_validation_rejected_total",
    "Total number of add-to-cart attempts rejected by catalog validation",
    ["reason"],
)
