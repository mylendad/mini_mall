"""Промежуточное ПО для сквозной трассировки HTTP-запросов.

Добавляет ``request_id`` и ``correlation_id`` в контекст structlog и в
заголовки ответа, обеспечивая связь логов одного запроса между сервисами.
"""
import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Пробрасывает или генерирует ``request_id`` и ``correlation_id``.

    Принимает ``X-Request-ID`` и ``X-Correlation-ID`` из заголовков запроса;
    при отсутствии генерирует новые значения. Идентификаторы связываются с
    контекстом structlog и возвращаются в заголовках ответа.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Обрабатывает запрос, связывая контекст и замеряя время.

        Параметры:
            request: Входящий HTTP-запрос.
            call_next: Следующий обработчик в цепочке middleware.

        Возвращает:
            HTTP-ответ с заголовками ``X-Request-ID`` и ``X-Correlation-ID``.
        """
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            correlation_id=correlation_id,
        )

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        return response
