"""Шаблон минимального микросервиса FastAPI.

Используется как отправная точка для новых сервисов: health-эндпоинты,
Prometheus-метрики и стартовая конфигурация логирования structlog.
"""
import asyncio
import signal
import structlog
from fastapi import FastAPI
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

logger = structlog.get_logger()

def create_app(service_name: str = "service") -> FastAPI:
    app = FastAPI(title=service_name, version="1.0.0")

    shutdown_event = asyncio.Event()

    @app.on_event("startup")
    async def startup_event():
        logger.info("Starting up application...", service=service_name)

    @app.on_event("shutdown")
    async def shutdown_event_handler():
        logger.info("Graceful shutdown initiated...", service=service_name)
        # Simulate closing DB pools, Kafka, Redis connections gracefully
        await asyncio.sleep(0.1)
        logger.info("All connections closed successfully.")

    @app.get("/health/live")
    async def health_live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def health_ready():
        return {"status": "ready"}

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
