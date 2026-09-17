## Purpose

Defines the requirements for the autonomous Authentication Service (`01-auth-service`), including database isolation, user lifecycle, JWT access tokens, opaque refresh tokens with DB hashing, concurrency-safe rotation, reuse detection, idempotent logout, and secure REST API endpoints.

## ADDED Requirements

### Requirement: Authentication Service Autonomy and Stack

The Authentication Service MUST be an autonomous Python 3.12+ FastAPI application located under `services/auth/` using PostgreSQL, SQLAlchemy async, asyncpg, Alembic, PyJWT (HS256 with JWT_SECRET), and `passlib[bcrypt]`. It SHALL NOT use Redis for auth blacklists, nor allow alternative JWT algorithms or password hash libraries.

#### Scenario: Tech stack validation

- **WHEN** the auth service is initialized and configured
- **THEN** it uses exclusively FastAPI, SQLAlchemy async, asyncpg, Alembic, PyJWT (HS256), and passlib[bcrypt] without optional alternatives or blacklist redis storage.

### Requirement: User Entity and Model

The service MUST manage users in a PostgreSQL table `users` containing `id` (UUID PK), `email` (unique, indexed, not null), `password_hash` (not null), `roles` (array/JSON of strings, not null, default `["customer"]`), `is_active` (boolean, not null, default true), `created_at`, and `updated_at`. Single role fields are strictly prohibited.

#### Scenario: User registration data integrity

- **WHEN** a user is registered with valid credentials
- **THEN** a user record is persisted with a UUID ID, hashed password, default `["customer"]` roles, and active status.

### Requirement: Refresh Token Entity and Cascade Deletion

The service MUST manage refresh tokens in a PostgreSQL table `refresh_tokens` containing `id` (UUID PK), `user_id` (FK to `users.id` with `ON DELETE CASCADE`), `token_hash` (unique, indexed, not null), `expires_at`, `is_revoked`, and `created_at`.

#### Scenario: Cascade deletion on user removal

- **WHEN** a user record is deleted from the `users` table
- **THEN** all associated refresh tokens in `refresh_tokens` are automatically deleted via cascading foreign key constraints.

### Requirement: JWT Access Token Structure and TTL

Access tokens MUST be JWTs signed using PyJWT with algorithm `HS256` and a strong `JWT_SECRET`. The payload MUST contain ONLY `sub` (user id), `roles` (array of strings), `exp`, `iat`, and `jti`. Inclusion of email, passwords, PII, billing, cart, or session information is strictly prohibited. Default TTL is 15 minutes.

#### Scenario: Access token verification

- **WHEN** an access token is generated or verified
- **THEN** it validates successfully under HS256, contains strictly the allowed claims without PII, and respects the 15-minute TTL.

### Requirement: Opaque Refresh Token and Hashing

Refresh tokens MUST NOT be JWTs. They MUST be opaque cryptographically secure random strings generated via `secrets.token_urlsafe(64)` with a default TTL of 7 days. Only their cryptographic hash MUST be stored in the `refresh_tokens` table.

#### Scenario: Refresh token storage

- **WHEN** a refresh token is issued during login or refresh
- **THEN** the plain token is returned to the client while only its hash is persisted in the database.

### Requirement: Concurrency-Safe Refresh Token Rotation

When processing `POST /api/v1/auth/refresh`, the service MUST find the refresh token by its hash within a database transaction, lock the row using `SELECT ... FOR UPDATE`, verify `is_revoked`, `expires_at`, and user `is_active`. If valid, it MUST mark the old token as revoked, create a new refresh token, store its hash, issue a new Access JWT, commit, and return the new pair. Concurrent requests for the same token must allow only one successful rotation.

#### Scenario: Concurrent refresh requests

- **WHEN** multiple concurrent refresh requests are submitted with the same refresh token
- **THEN** exactly one request successfully rotates the token while subsequent attempts fail due to locking or revocation.

### Requirement: Refresh Token Reuse Detection

If during `POST /api/v1/auth/refresh` a refresh token is presented whose record already has `is_revoked == true`, the service MUST detect a token reuse/replay attack, revoke ALL active refresh tokens belonging to that user, and return `401 Unauthorized`.

#### Scenario: Replay attack mitigation

- **WHEN** an already revoked refresh token is presented to `/refresh`
- **THEN** all active refresh tokens for that user are immediately revoked and a 401 Unauthorized error is returned.

### Requirement: Inactive User Restrictions

If a user's `is_active` status is `false`, both `POST /api/v1/auth/login` and `POST /api/v1/auth/refresh` MUST return `401 Unauthorized`. Previously issued Access JWTs remain valid until their expiration without Redis blacklisting.

#### Scenario: Deactivated user authentication attempt

- **WHEN** an inactive user attempts login or token refresh
- **THEN** the service rejects the request with 401 Unauthorized.

### Requirement: Idempotent Logout

`POST /api/v1/auth/logout` MUST accept a refresh token. Existing active tokens are revoked (`is_revoked = true`), while already revoked or unknown tokens result in `204 No Content`, ensuring idempotency. Access JWTs are not blacklisted.

#### Scenario: Logout with unknown or revoked token

- **WHEN** a client calls logout with an unknown or already revoked refresh token
- **THEN** the service returns 204 No Content without error.

### Requirement: Standard Authentication and User Endpoints

The service MUST expose the following REST endpoints:

- `POST /api/v1/auth/register`: Register user, returns `201 Created` with user id, email, and roles (duplicate email returns `409 Conflict`).
- `POST /api/v1/auth/login`: Authenticate credentials, returns `200 OK` with `access_token`, `refresh_token`, and `token_type` (invalid credentials or inactive user returns `401 Unauthorized`).
- `POST /api/v1/auth/refresh`: Rotate refresh token, returns `200 OK` with new token pair (invalid/expired/revoked/reused token returns `401 Unauthorized`).
- `POST /api/v1/auth/logout`: Revoke refresh token, returns `204 No Content`.
- GET /api/v1/users/me: Requires authenticated identity via trusted internal headers (X-User-ID, X-User-Roles) injected by the API Gateway, returns user id, email, and roles (401 if headers are missing/invalid).`GET /api/v1/users/me`: Requires authenticated identity via Bearer token, returns user id, email, and roles (`401` if unauthenticated

#### Scenario: Standard endpoint contracts

- **WHEN** HTTP requests are made to authentication and user endpoints
- **THEN** they adhere strictly to the specified request/response JSON schemas and HTTP status codes.
