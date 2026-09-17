"""Интеграционные тесты auth-сервиса на Testcontainers.

Поднимают реальный PostgreSQL в контейнере, создают схему и прогоняют
API-сценарии: регистрация/логин, ротация refresh-токена, конкурентная
ротация, повторное использование токена и идемпотентный логаут.
"""
import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# TODO: `testcontainers.postgres` is deprecated. Migrate to
# `testcontainers.community.postgres` (import `PostgresContainer` from there).
from testcontainers.postgres import PostgresContainer

from app import database, main
from app.config import settings
from app.database import Base, get_db
from app.main import app


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:15-alpine", username="test", password="test", dbname="test") as postgres:
        yield postgres

@pytest_asyncio.fixture(scope="session")
async def db_engine(postgres_container):
    url = postgres_container.get_connection_url(driver="asyncpg")
    settings.database_url = url
    engine = create_async_engine(url, future=True, echo=False)
    database.engine = engine
    database.async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    main.engine = engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def db_session(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()

@pytest_asyncio.fixture
async def client(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    
    async def override_get_db():
        async with async_session() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_health_checks(client):
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}

    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

@pytest.mark.asyncio
async def test_register_and_login(client):
    email = "test@example.com"
    password = "securepassword123"

    # Register
    response = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == email
    assert data["roles"] == ["customer"]

    # Duplicate register -> 409
    response = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 409

    # Login
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    tokens = response.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens

    # Get /users/me
    access_token = tokens["access_token"]
    response = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})
    assert response.status_code == 200
    user_me = response.json()
    assert user_me["email"] == email

    # Refresh token
    refresh_token = tokens["refresh_token"]
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    new_tokens = response.json()
    assert "access_token" in new_tokens
    assert "refresh_token" in new_tokens

    # Logout
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": new_tokens["refresh_token"]})
    assert response.status_code == 204

@pytest.mark.asyncio
async def test_token_reuse_detection(client):
    email = "reuse@example.com"
    password = "securepassword123"

    await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    tokens = login_resp.json()
    ref_token_1 = tokens["refresh_token"]

    # First refresh succeeds
    refresh_resp_1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": ref_token_1})
    assert refresh_resp_1.status_code == 200
    ref_token_2 = refresh_resp_1.json()["refresh_token"]

    # Reusing ref_token_1 (already revoked) triggers reuse detection -> 401
    reuse_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": ref_token_1})
    assert reuse_resp.status_code == 401

    # ref_token_2 should also be revoked now due to reuse detection
    try_ref_2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": ref_token_2})
    assert try_ref_2.status_code == 401

@pytest.mark.asyncio
async def test_concurrent_refresh_single_wins(client):
    email = "concurrent@example.com"
    password = "securepassword123"

    await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    refresh_token = login_resp.json()["refresh_token"]

    resp_1, resp_2 = await asyncio.gather(
        client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token}),
        client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token}),
    )
    assert sorted([resp_1.status_code, resp_2.status_code]) == [200, 401]

@pytest.mark.asyncio
async def test_logout_idempotent(client):
    email = "logout@example.com"
    password = "securepassword123"

    await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    refresh_token = login_resp.json()["refresh_token"]

    resp_1 = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert resp_1.status_code == 204

    resp_2 = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert resp_2.status_code == 204

    refresh_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 401
