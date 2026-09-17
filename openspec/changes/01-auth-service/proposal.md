## Why

Establish the autonomous Authentication Service (`01-auth-service`) adhering strictly to foundation architectural invariants, database-per-service isolation, and secure modern authentication practices (PyJWT access tokens, opaque cryptographically secure refresh tokens with DB hash storage, concurrency-safe rotation, reuse detection, and robust error handling).

## What Changes

- Create `services/auth/` as an autonomous Python 3.12+ FastAPI microservice with its own isolated configuration, dependencies (`pyproject.toml`), container definitions (`Dockerfile`), Alembic database migrations, and pytest integration tests using Testcontainers.
- Implement database models `users` and `refresh_tokens` in PostgreSQL with proper constraints, cascade deletes, and unique/indexed fields.
- Implement secure authentication endpoints:
  - `POST /api/v1/auth/register`: Register new user with email and password, hashing via `passlib[bcrypt]`, returning user details without password.
  - `POST /api/v1/auth/login`: Authenticate user credentials and inactive status check, returning access JWT and opaque refresh token.
  - `POST /api/v1/auth/refresh`: Concurrency-safe refresh token rotation with `SELECT ... FOR UPDATE`, token reuse detection that revokes all tokens for the user upon reuse of an already revoked token, and returning a new token pair.
  - `POST /api/v1/auth/logout`: Idempotent revocation of active refresh tokens.
  - `GET /api/v1/users/me`: Protected endpoint returning authenticated user identity.
- Establish strict token specifications:
  - Access Token: PyJWT using HS256 with `JWT_SECRET`, containing only `sub`, `roles`, `exp`, `iat`, `jti`, with 15-minute TTL. No PII or sensitive data.
  - Refresh Token: Opaque string via `secrets.token_urlsafe(64)`, 7-day TTL, hashed in DB.
- Integrate shared technical libraries (`libs/common/`) for logging, configuration, error handling, and observability.

## Capabilities

### New Capabilities

- `auth-service`: Autonomous authentication microservice managing users, credentials, JWT access tokens, opaque refresh tokens, secure rotation, token reuse detection, logout, and protected user endpoints.

### Modified Capabilities

- None

## Impact

- Introduces a new autonomous microservice `services/auth/` with its own PostgreSQL database schema and migrations.
- Establishes the primary authentication and user identity boundary for subsequent microservices (Cart, Order, Payment, etc.).
- Adheres strictly to foundation standards and rules (no Redis blacklist, no PII in JWT, zero cross-database queries).
