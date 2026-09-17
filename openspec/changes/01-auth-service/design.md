## Architecture and Design

### 1. Overview & Service Boundary
The `01-auth-service` is an autonomous microservice located at `services/auth/` adhering to the Foundation architecture. It owns its dedicated PostgreSQL database (`mini_mall_auth`) and handles user registration, credential authentication, JWT access token issuance, opaque refresh token rotation, token reuse detection, logout, and user profile retrieval (`GET /api/v1/users/me`).

### 2. Technology Stack & Components
- **Framework**: FastAPI (Python 3.12+)
- **Database ORM & Migrations**: SQLAlchemy async, asyncpg, Alembic
- **Password Hashing**: `passlib[bcrypt]`
- **JWT Handling**: PyJWT (Algorithm: `HS256`, secret injected via environment variable `JWT_SECRET`)
- **Random Generation**: Python standard library `secrets.token_urlsafe(64)` for refresh tokens
- **Testing**: Pytest with Testcontainers for PostgreSQL integration testing

### 3. Database Schema Design

#### Table: `users`
- `id`: UUID (Primary Key, default `uuid4`)
- `email`: VARCHAR(255) (UNIQUE, INDEXED, NOT NULL)
- `password_hash`: VARCHAR(255) (NOT NULL)
- `roles`: JSON / VARCHAR[] (NOT NULL, default `["customer"]`)
- `is_active`: BOOLEAN (NOT NULL, default `true`)
- `created_at`: TIMESTAMP (NOT NULL, default `utcnow`)
- `updated_at`: TIMESTAMP (NOT NULL, default `utcnow`)

#### Table: `refresh_tokens`
- `id`: UUID (Primary Key, default `uuid4`)
- `user_id`: UUID (Foreign Key references `users.id`, `ON DELETE CASCADE`, NOT NULL)
- `token_hash`: VARCHAR(255) (UNIQUE, INDEXED, NOT NULL)
- `expires_at`: TIMESTAMP (NOT NULL)
- `is_revoked`: BOOLEAN (NOT NULL, default `false`)
- `created_at`: TIMESTAMP (NOT NULL, default `utcnow`)

### 4. Authentication & Token Lifecycle

#### Access Token (JWT)
- Signed with `HS256` and `JWT_SECRET`.
- Payload structure:
  ```json
  {
    "sub": "<user_id_uuid>",
    "roles": ["customer"],
    "exp": 1711900800,
    "iat": 1711899900,
    "jti": "<uuid_token_id>"
  }
  ```
- TTL: 15 minutes.
- Stateless verification at downstream consumers/gateway via public/shared secret validation. No Redis blacklist.

#### Refresh Token (Opaque)
- Format: `secrets.token_urlsafe(64)`.
- Stored as cryptographic hash (e.g. SHA-256) in `refresh_tokens.token_hash`.
- TTL: 7 days.

### 5. Core Algorithms

#### Concurrency-Safe Rotation (`POST /api/v1/auth/refresh`)
1. Compute SHA-256 hash of incoming opaque refresh token.
2. Open DB transaction.
3. Query `refresh_tokens` filtering by hash and lock row with `SELECT ... FOR UPDATE`.
4. If row not found -> raise `401 Unauthorized`.
5. Check if `is_revoked == true`:
   - **Reuse Detection Triggered**: Immediately set `is_revoked = true` for ALL refresh tokens where `user_id = token.user_id`. Commit transaction. Return `401 Unauthorized`.
6. Check if `expires_at < utcnow()` -> raise `401 Unauthorized`.
7. Fetch associated user, verify user exists and `is_active == true` -> if false, raise `401 Unauthorized`.
8. Mark current refresh token as `is_revoked = true`.
9. Generate new opaque refresh token, compute its hash, persist new record in `refresh_tokens`.
10. Generate new Access JWT.
11. Commit transaction and return new token pair (`200 OK`).

#### Logout (`POST /api/v1/auth/logout`)
1. Compute hash of incoming refresh token.
2. Find record in `refresh_tokens`.
3. If found and `is_revoked == false`, set `is_revoked = true` and commit.
4. If not found or already revoked, do nothing.
5. Return `204 No Content` (idempotent).

### 6. Directory Structure (`services/auth/`)
```
services/auth/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   └── api/
├── alembic/
├── Dockerfile
├── pyproject.toml
└── tests/
```
