"""Фикстуры тестов инвентаря: Testcontainers PostgreSQL (+ Kafka по запросу).

PostgreSQL поднимается один раз на сессию, к нему применяются реальные
миграции Alembic (``alembic upgrade head``), после чего движок и фабрика
сессий переключаются на контейнер. Kafka — опциональная сессионная
фикстура (для тестов потребителя и релея); без Docker/образа тесты Kafka
пропускаются с понятным сообщением.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

SERVICE_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = SERVICE_DIR.parents[1]
_ALEMBIC = os.environ.get("ALEMBIC_BIN", str(_REPO_ROOT / ".venv/bin/alembic"))


def _run_alembic(*args: str, database_url: str) -> subprocess.CompletedProcess:
    """Запускает alembic в подпроцессе (env.py использует asyncio.run)."""
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [_ALEMBIC, "-c", "alembic.ini", *args],
        cwd=str(SERVICE_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_ok(result: subprocess.CompletedProcess, what: str) -> None:
    assert result.returncode == 0, (
        f"alembic {what} failed:\n{result.stdout}\n{result.stderr}"
    )


@pytest.fixture(scope="session")
def postgres_container():
    """Сессионный PostgreSQL-контейнер (postgres:16-alpine)."""
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(
        "postgres:16-alpine", username="test", password="test", dbname="test"
    ) as postgres:
        yield postgres


@pytest_asyncio.fixture(scope="session")
async def db_engine(postgres_container):
    """Движок к контейнеру после реальных миграций Alembic."""
    import app.main  # регистрирует create_app() и зависимости
    from app import database
    from app.config import settings

    url = postgres_container.get_connection_url(driver="asyncpg")
    settings.database_url = url

    result = _run_alembic("upgrade", "head", database_url=url)
    _assert_ok(result, "upgrade head")

    engine = create_async_engine(url, future=True, echo=False)
    database.engine = engine
    database.async_session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    app.main.engine = engine  # health/ready использует именно этот движок

    yield engine

    result = _run_alembic("downgrade", "base", database_url=url)
    _assert_ok(result, "downgrade base")
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    """Отдельная сессия на тест."""
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_engine) -> AsyncIterator[object]:
    """HTTP-клиент на приложении инвентаря с переопределённым get_db."""
    from httpx import ASGITransport, AsyncClient

    from app.database import get_db
    from app.main import app

    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_db():
        async with async_session() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def kafka_container():
    """Сессионный Kafka-контейнер (confluentinc/cp-kafka:7.6.0, KRaft)."""
    from testcontainers.community.kafka import KafkaContainer

    try:
        container = KafkaContainer("confluentinc/cp-kafka:7.6.0")
        # Увеличенный startup_timeout: брокер на медленной машине стартует
        # дольше дефолтных 30с (KRaft-инициализация, первый лог-флаш).
        container.start(timeout=180)
        yield container
        container.stop()
    except Exception as exc:  # noqa: BLE001 - докладывать о невозможности запуска
        pytest.skip(f"Cannot start Kafka container: {exc}")


@pytest.fixture
def kafka_bootstrap(kafka_container) -> Iterator[str]:
    """Bootstrap-адрес контейнера Kafka с переключением настроек сервиса."""
    from app.config import settings

    url = kafka_container.get_bootstrap_server()
    original = settings.kafka_bootstrap_servers
    settings.kafka_bootstrap_servers = url
    yield url
    settings.kafka_bootstrap_servers = original
