"""Точка входа FastAPI-приложения сервиса каталога.

Собирает приложение через :func:`create_app`: роутеры категорий, продуктов,
поиска и админ-эндпоинтов (``/products/search`` регистрируется раньше
``/products/{product_id}``), health-эндпоинты, метрики Prometheus и единые
обработчики ошибок :class:`common.errors.ErrorResponse`. Lifespan поднимает
релей outbox-синхронизации PG -> ES, Redis-клиент read-through кэша и
OpenTelemetry-инструментацию (FastAPI + SQLAlchemy) и останавливает их при
завершении.
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from common.errors import ErrorDetail, ErrorResponse
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

from app import cache
from app.api.admin import router as admin_router
from app.api.categories import router as categories_router
from app.api.products import router as products_router
from app.api.search import router as search_router
from app.config import settings
from app.database import engine
from app.elasticsearch import ensure_index, es_client
from app.services.relay import relay_job

logger = structlog.get_logger()


def _setup_tracing(app: FastAPI) -> None:
    """Инициализирует OpenTelemetry, если задан ``OTEL_EXPORTER_OTLP_ENDPOINT``.

    Инструментируются FastAPI (входящие HTTP-запросы, W3C traceparent
    извлекается автоматически глобальным пропагатором) и SQLAlchemy
    (синхронный движок async-обёртки). Экспорт — OTLP/HTTP в Jaeger
    (BatchSpanProcessor с коротким таймаутом; без эндпоинта трейсинг выключен).
    """
    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
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
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine, tracer_provider=provider
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл: логи, трейсинг, Redis, индекс ES, релей, закрытие пулов."""
    setup_logging(settings.log_level)
    _setup_tracing(app)
    cache.init()
    try:
        await ensure_index()
    except Exception as exc:  # noqa: BLE001 - ES недоступен - только предупреждение
        logger.warning("index.ensure_failed", error=str(exc))
    stop_event = asyncio.Event()
    relay_task = asyncio.create_task(relay_job(stop_event))
    app.state.relay_task = relay_task
    try:
        yield
    finally:
        stop_event.set()
        relay_task.cancel()
        try:
            await relay_task
        except asyncio.CancelledError:
            pass
        await cache.close()
        await es_client.close()
        await engine.dispose()


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
    """Создаёт и настраивает FastAPI-приложение каталога.

    Порядок инклюда роутеров важен: ``search_router`` (GET ``/products/search``)
    подключается до ``products_router`` (GET ``/products/{product_id}``).
    """
    app = FastAPI(title="Catalog Service", version="1.0.0", lifespan=lifespan)

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(PrometheusMetricsMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict):
            error_data = exc.detail
        else:
            error_data = {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "details": None,
            }
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
            ErrorDetail(
                code="VALIDATION_ERROR",
                message="Request validation failed",
                details={"errors": errors},
            ),
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
        except Exception as exc:  # noqa: BLE001 - проверка готовности
            return JSONResponse(
                status_code=503, content={"status": "unhealthy", "detail": str(exc)}
            )

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(search_router)
    app.include_router(categories_router)
    app.include_router(products_router)
    app.include_router(admin_router)

    return app


app = create_app()
