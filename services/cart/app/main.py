"""Точка входа FastAPI-приложения cart-сервиса (задачи 1.3/1.4).

Собирает приложение через :func:`create_app`: роутер корзины, health-эндпоинты
(``/health/ready`` пингует Redis), метрики Prometheus и единые обработчики
ошибок :class:`common.errors.ErrorResponse`. Lifespan поднимает Redis-клиент,
httpx-клиент Catalog и OpenTelemetry-инструментацию (FastAPI + httpx для
сквозной трассировки до Catalog) и закрывает их при выключении — SIGTERM
uvicorn останавливает приём трафика, дожидается in-flight запросов и запускает
shutdown (graceful drain), после чего пулы закрываются.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from common.errors import (
    HTTP_ERROR,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    error_detail,
)
from common.logging import setup_logging
from common.middleware import RequestIDMiddleware
from common.observability import PrometheusMetricsMiddleware
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.api.cart import router as cart_router
from app.config import settings

logger = structlog.get_logger()


def _setup_tracing(app: FastAPI) -> None:
    """Инициализирует OpenTelemetry, если задан ``OTEL_EXPORTER_OTLP_ENDPOINT``.

    Инструментируются FastAPI (входящие запросы, W3C tracecontext извлекается
    глобальным пропагатором) и httpx (исходящие вызовы Catalog продолжают тот
    же трейс). Экспорт — OTLP/HTTP в Jaeger; без эндпоинта трейсинг выключен.
    """
    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.app_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=5))
    )
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл: логи, трейсинг, Redis, httpx Catalog, их закрытие."""
    setup_logging(settings.log_level)
    _setup_tracing(app)
    from app.infrastructure.catalog_http import close as close_catalog_http
    from app.infrastructure.catalog_http import init as init_catalog_http
    from app.infrastructure.redis_client import close as close_redis
    from app.infrastructure.redis_client import init as init_redis

    init_redis()
    init_catalog_http()
    logger.info("cart_service_started", app_name=settings.app_name)
    try:
        yield
    finally:
        # SIGTERM: uvicorn уже не принимает новых соединений и дождался
        # in-flight запросов; здесь закрываются пулы соединений.
        logger.info("cart_service_stopping")
        await close_catalog_http()
        await close_redis()


def _request_id(request: Request) -> str:
    """Возвращает ``request_id`` из state или заголовка ``X-Request-ID``."""
    return (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or "unknown"
    )


def _error_response(
    status_code: int, error: ErrorDetail, request: Request
) -> JSONResponse:
    """Собирает ответ об ошибке в формате :class:`common.errors.ErrorResponse`."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=error, request_id=_request_id(request)
        ).model_dump(),
    )


def create_app() -> FastAPI:
    """Создаёт и настраивает FastAPI-приложение cart-сервиса."""
    app = FastAPI(title="Cart Service", version="1.0.0", lifespan=lifespan)

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(PrometheusMetricsMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict):
            error_data = exc.detail
        else:
            # ``HTTP_ERROR`` намеренно вне ``ErrorCode``: это сквозной код для
            # чужих HTTPException, у которых статус и текст задаёт сам exception.
            error_data = error_detail(HTTP_ERROR, message=str(exc.detail))
        return _error_response(exc.status_code, ErrorDetail(**error_data), request)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        errors = [
            jsonable_encoder({k: v for k, v in e.items() if k != "ctx"})
            for e in exc.errors()
        ]
        return _error_response(
            422,
            error_detail(ErrorCode.VALIDATION_ERROR, details={"errors": errors}),
            request,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "unhandled_exception",
            method=request.method,
            path=request.url.path,
            error=str(exc),
        )
        return _error_response(
            500,
            error_detail(ErrorCode.INTERNAL_ERROR),
            request,
        )

    @app.get("/health/live")
    async def health_live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def health_ready():
        from app.infrastructure.redis_client import get_client

        try:
            client = get_client()
            await client.ping()
            return {"status": "ready"}
        except Exception as exc:  # noqa: BLE001 - проверка готовности
            # Внутренние детали (URL, топология) наружу не раскрываются.
            logger.warning("health_ready_failed", error=str(exc))
            return JSONResponse(
                status_code=503, content={"status": "unhealthy"}
            )

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(cart_router)

    return app


app = create_app()
