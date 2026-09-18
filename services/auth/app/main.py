"""Точка входа FastAPI-приложения сервиса аутентификации.

Собирает приложение (роутер auth, healthcheck-эндпоинты, метрики Prometheus
и обработчики ошибок) через :func:`create_app` и создаёт глобальный
экземпляр ``app`` для ASGI-сервера.
"""
from contextlib import asynccontextmanager

from app.api.auth import router as auth_router
from app.config import settings
from app.database import engine
from common.errors import ErrorDetail, ErrorResponse
from common.logging import setup_logging
from common.middleware import RequestIDMiddleware
from common.observability import PrometheusMetricsMiddleware
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управляет жизненным циклом приложения.

    На старте настраивает структурированное логирование (structlog),
    при завершении освобождает пул соединений с базой данных.
    """
    setup_logging(settings.log_level)
    yield
    await engine.dispose()


def _request_id(request: Request) -> str:
    """Возвращает ``request_id`` из state или заголовка запроса.

    Значение кладётся в ``request.state`` middleware :class:`RequestIDMiddleware`;
    при отсутствии используется заголовок ``X-Request-ID``.
    """
    return getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or "unknown"


def _error_response(status_code: int, error: ErrorDetail, request: Request) -> JSONResponse:
    """Формирует ответ об ошибке в стандартном формате.

    Собирает конверт :class:`common.errors.ErrorResponse` с ``request_id``
    из запроса.

    Параметры:
        status_code: HTTP-статус ответа.
        error: Блок ``error``.
        request: Текущий запрос (источник ``request_id``).

    Возвращает:
        Ответ :class:`JSONResponse` в формате ``ErrorResponse``.
    """
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=error, request_id=_request_id(request)).model_dump(),
    )


def create_app() -> FastAPI:
    """Создаёт и настраивает FastAPI-приложение.

    Регистрирует роутер аутентификации, health-эндпоинты, метрики и
    обработчики ошибок (HTTPException, 422, 500) с единым форматом
    :class:`ErrorResponse`.

    Возвращает:
        Настроенный экземпляр ``FastAPI``.
    """
    app = FastAPI(title="Auth Service", version="1.0.0", lifespan=lifespan)

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(PrometheusMetricsMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict):
            error_data = exc.detail
        else:
            error_data = {"code": "HTTP_ERROR", "message": str(exc.detail), "details": None}
        return _error_response(exc.status_code, ErrorDetail(**error_data), request)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return _error_response(
            422,
            ErrorDetail(code="VALIDATION_ERROR", message="Request validation failed", details=exc.errors()),
            request,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return _error_response(
            500,
            ErrorDetail(code="INTERNAL_ERROR", message="Internal server error"),
            request,
        )

    @app.get("/health/live")
    async def health_live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def health_ready():
        try:
            async with engine.connect() as conn:
                await conn.exec_driver_sql("SELECT 1")
            return {"status": "ready"}
        except Exception as e:
            return JSONResponse(status_code=503, content={"status": "unhealthy", "detail": str(e)})

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(auth_router)

    return app

app = create_app()