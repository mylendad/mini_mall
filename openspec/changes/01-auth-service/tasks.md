## Implementation Tasks

- [ ] Scaffolding and Configuration

  - [ ] Create `services/auth/` directory structure (`app/`, `alembic/`, `tests/`).
  - [ ] Configure `pyproject.toml` for `auth-service` with FastAPI, SQLAlchemy, asyncpg, Alembic, PyJWT, passlib[bcrypt], and test dependencies.
  - [ ] Implement Pydantic settings in `services/auth/app/config.py` inheriting from shared base settings and adding `JWT_SECRET`, database URL, and token TTL configurations.
  - [ ] Create `Dockerfile` using multi-stage builds and non-root execution.
- [ ] Database Setup and Models

  - [ ] Configure asynchronous database engine and session factory in `services/auth/app/database.py`.
  - [ ] Define SQLAlchemy model for `users` (`id`, `email`, `password_hash`, `roles`, `is_active`, timestamps) with unique/indexed constraints.
  - [ ] Define SQLAlchemy model for `refresh_tokens` (`id`, `user_id` with CASCADE delete, `token_hash`, `expires_at`, `is_revoked`, `created_at`) with unique/indexed token hash.
  - [ ] Initialize Alembic and generate initial migration for `users` and `refresh_tokens` tables.
- [ ] Core Authentication Logic and Repositories

  - [ ] Implement password hashing and verification utilities using `passlib[bcrypt]`.
  - [ ] Implement JWT access token generation and verification utilities using PyJWT (`HS256`, 15-minute TTL, strict claims).
  - [ ] Implement opaque refresh token generation (`secrets.token_urlsafe(64)`) and hashing.
  - [ ] Implement user repository and refresh token repository with concurrency-safe `SELECT ... FOR UPDATE` locking.
- [ ] API Endpoints Implementation

  - [ ] Implement `POST /api/v1/auth/register` (handles duplicate email -> 409, returns user details).
  - [ ] Implement `POST /api/v1/auth/login` (validates credentials and active status, returns access and refresh tokens).
  - [ ] Implement `POST /api/v1/auth/refresh` (concurrency-safe rotation, refresh token reuse detection revoking all user tokens -> 401).
  - [ ] Implement `POST /api/v1/auth/logout` (idempotent refresh token revocation -> 204).
  - [ ] Define Pydantic request schemas with strict validation (EmailStr for emails, minimum 8 characters for passwords).Implement `GET /api/v1/users/me` (Bearer token authentication dependency, returns user profile
  - [ ] Wire up FastAPI application entrypoint in services/auth/app/main.py including /health/live and /health/ready (with DB ping) endpoints, and error handlers.
- [ ] Testing and Verification

  - [ ] Write unit tests for password hashing, JWT generation, and token rotation logic.
  - [ ] Write Testcontainers integration tests covering registration, login, token refresh, concurrent rotation, token reuse detection (revoking all tokens), logout idempotency, and protected user endpoints.
  - [ ] Verify build, linting, and test execution.
