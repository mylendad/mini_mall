"""Подключение к PostgreSQL через асинхронный SQLAlchemy.

Модуль предоставляет глобальный асинхронный движок, фабрику сессий,
базовый класс декларативных моделей и FastAPI-зависимость :func:`get_db`
для выдачи сессии в обработчиках запросов.
"""
from app.config import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

engine = create_async_engine(settings.database_url, echo=False, future=True)
"""Асинхронный движок SQLAlchemy для PostgreSQL (общий на приложение)."""

async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
"""Фабрика асинхронных сессий; создаёт сессию с ``expire_on_commit=False``."""

Base = declarative_base()
"""Базовый класс декларативных моделей (используется моделями и Alembic)."""

async def get_db() -> AsyncSession:
    """FastAPI-зависимость: выдаёт асинхронную сессию на время запроса.

    Сессия открывается для каждого запроса и закрывается после него.
    Используется через ``Depends(get_db)`` в эндпоинтах.
    """
    async with async_session_maker() as session:
        yield session
