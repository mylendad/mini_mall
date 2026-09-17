"""Точка входа FastAPI-приложения сервиса аутентификации.

Собирает приложение (роутер auth, healthcheck-эндпоинты, метрики Prometheus
и обработчики ошибок) через :func:`create_app` и создаёт глобальный
экземпляр ``app`` для ASGI-сервера.
"""
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.api.auth import router as auth_router
from app.database import engine


def create_app() -> FastAPI:
    """Создаёт и настраивает FastAPI-приложение.

    Регистрирует роутер аутентификации, health-эндпоинты, метрики и
    обработчики ошибок (422/500) с единым форматом :class:`ErrorResponse`.

    Возвращает:
        Настроенный экземпляр ``FastAPI``.
    """
    app = FastAPI(title="Auth Service", version="1.0.0")

    # TODO: `@app.on_event` is deprecated. Migrate startup/shutdown logic to a
    # lifespan context manager (asgi-lifespan).
    @app.on_event("startup")
    async def startup_event():
        pass

    @app.on_event("shutdown")
    async def shutdown_event():
        await engine.dispose()

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": exc.errors(),
                },
                "request_id": str(uuid.uuid4()),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "INTERNAL_ERROR", "message": "Internal server error"},
                "request_id": str(uuid.uuid4()),
            },
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
