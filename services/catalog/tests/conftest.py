"""Фикстуры тестов каталога: Testcontainers PostgreSQL + Elasticsearch.

PostgreSQL поднимается один раз на сессию, к нему применяются реальные
миграции Alembic (``alembic upgrade head``), после чего движок и фабрика
сессий переключаются на контейнер. Elasticsearch — отдельная сессионная
фикстура; клиент ``app.elasticsearch.es_client`` переключается на контейнер
только для тестов поиска (если контейнер ES невозможен — тесты поиска
пропускаются с понятным сообщением).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

SERVICE_DIR = Path(__file__).resolve().parents[1]
_ALEMBIC = os.environ.get(
    "ALEMBIC_BIN", "/home/mylendad/Desktop/Projects/mini_mall_2/.venv/bin/alembic"
)


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
    """HTTP-клиент на приложении каталога с переопределённым get_db."""
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
def elasticsearch_container():
    """Сессионный Elasticsearch-контейнер; при невозможности — skip.

    Elasticsearch 8.12.2 запускается с выключенной безопасностью
    (``xpack.security.enabled=false``) и ограниченной памятью, чтобы влезать
    в CI/локальную среду.
    """
    from testcontainers.community.elasticsearch import ElasticSearchContainer

    try:
        container = ElasticSearchContainer(
            "elasticsearch:8.12.2",
            mem_limit="2G",
        )
        container.with_env("ES_JAVA_OPTS", "-Xms512m -Xmx512m")
        # На машинах с почти занятым диском ES по умолчанию не аллоцирует
        # шарды (high watermark 90% / <22.3Gb free) и индекс застревает в red.
        container.with_env("cluster.routing.allocation.disk.watermark.low", "90%")
        container.with_env("cluster.routing.allocation.disk.watermark.high", "95%")
        container.with_env(
            "cluster.routing.allocation.disk.watermark.flood_stage", "98%"
        )
        container.start()
    except Exception as exc:  # noqa: BLE001 - докладовать о невозможности запуска
        pytest.skip(f"Cannot start Elasticsearch container: {exc}")
    yield container
    container.stop()


@pytest.fixture
def es_url(elasticsearch_container) -> str:
    """HTTP-URL контейнера Elasticsearch."""
    host = elasticsearch_container.get_container_host_ip()
    port = elasticsearch_container.get_exposed_port(elasticsearch_container.port)
    return f"http://{host}:{port}"


@pytest_asyncio.fixture
async def es_client(es_url) -> AsyncIterator[object]:
    """Переключает ``app.elasticsearch.es_client`` на контейнер и чистит после.

    Ждёт готовности ES (ping) до 60с: контейнер стартует быстрее, чем JVM
    отвечает на первый запрос.
    """
    from app import elasticsearch

    original = elasticsearch.es_client
    elasticsearch.es_client = elasticsearch.create_client(es_url, request_timeout=60.0)
    try:
        client = elasticsearch.es_client
        for _ in range(60):
            if await client.ping():
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Elasticsearch container did not become ready in 60s")
    except Exception:
        await elasticsearch.es_client.close()
        elasticsearch.es_client = original
        raise
    yield elasticsearch.es_client
    await elasticsearch.es_client.close()
    elasticsearch.es_client = original
