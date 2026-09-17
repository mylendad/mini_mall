## Context

See `proposal.md` for motivation. The project is a greenfield production-like e-commerce backend platform built as a hands-on distributed systems laboratory. It requires strict architectural rules across microservices, databases, messaging, and deployment tooling before any business service implementation begins.

## Goals / Non-Goals

**Goals:**
- Define standard repository structure (`services/`, `gateway/`, `libs/common/`, `infrastructure/`, `tests/`).
- Standardize the internal architecture of individual services (clean separation into `api/`, `domain/`, `application/`, `infrastructure/`, `models/`, `schemas/`).
- Specify technical contracts for `libs/common` (correlation ID middleware, structured JSON logging, event envelope, error handling).
- Formalize Kafka event contract schema, versioning, Outbox pattern, and Saga orchestration guidelines.
- Standardize local environment orchestration (Docker Compose) and production-like deployment manifests (Kubernetes, Helm, Ansible, Jenkins).
- Establish testing conventions (unit tests with isolated domain logic, integration tests using Testcontainers, load tests with k6).

**Non-Goals:**
- Implementing domain business logic for specific business services (Auth, Catalog, Cart, etc. will each be introduced in separate OpenSpec changes).
- Deploying live cloud infrastructure or managing live external cloud resources.
- Building frontend applications.

## Decisions

### Decision: Python 3.12+ and FastAPI for Backend Services
- **Choice**: Python 3.12+ across all services, using FastAPI for HTTP APIs and Pydantic v2 for data validation and settings management.
- **Rationale**: Provides high-performance asynchronous request handling, native OpenAPI documentation, and strict type safety.
- **Alternatives Considered**: 
  - Django / Django Ninja: Heavily coupled ORM and less flexible for microservices with non-relational or heterogeneous data stores.
  - Go / Node.js: Excluded because the project's educational focus is on modern Python distributed systems patterns.

### Decision: Service Layered Architecture
- **Choice**: Clean separation inside each service into `domain/` (pure business logic, no framework imports), `application/` (use cases, orchestrators, interfaces), `infrastructure/` (DB repositories, external clients, Kafka publishers/consumers), and `api/` (FastAPI routes and dependency injection).
- **Rationale**: Isolates business logic from external frameworks, enabling fast unit testing without mocks or database overhead.
- **Alternatives Considered**: Traditional flat MVC structure; rejected due to high coupling between HTTP handlers and database queries.

### Decision: Repository Organization and Shared Library Boundary
- **Choice**: Monorepo containing autonomous service folders (`services/<name>`) and a strictly limited shared technical library (`libs/common`). Each service has its own `pyproject.toml` and Dockerfile.
- **Rationale**: Maintains monorepo developer convenience while enforcing deployment and runtime isolation.
- **Alternatives Considered**: Multi-repo structure (harder to manage in early stages) or shared business logic library (strictly rejected to prevent tight coupling).

### Decision: Messaging and Distributed Transaction Patterns
- **Choice**: Apache Kafka for asynchronous domain events with a standardized JSON Event Envelope. Relational services use an Outbox table and background publisher to ensure atomicity. Checkout workflows use Saga Orchestration.
- **Rationale**: Avoids dual-write inconsistency and prevents distributed deadlocks. Orchestration provides explicit visibility into distributed multi-step transactions.
- **Alternatives Considered**: Two-Phase Commit (2PC) / distributed locks; rejected due to poor fault tolerance and latency.

### Decision: Database-per-Service
- **Choice**: Dedicated database per service (PostgreSQL for Auth, Catalog, Inventory, Order, Payment, Delivery; Redis for Cart; MongoDB for Notification; ClickHouse for Analytics; Elasticsearch for search projections).
- **Rationale**: Enforces single source of truth, eliminates cross-service SQL coupling, and allows tailoring storage engine to domain access patterns.

### Decision: Testing Strategy with Testcontainers
- **Choice**: Unit tests run in-memory; integration tests run against real PostgreSQL, Redis, Kafka, MongoDB, Elasticsearch, and ClickHouse containers spawned via `testcontainers-python`.
- **Rationale**: Eliminates flaky mocks and catches realistic SQL/driver/broker integration bugs without requiring complex pre-running host infrastructure.
- **Alternatives Considered**: Mocking DB and message brokers; rejected because mocks hide schema incompatibilities and concurrency race conditions.

## Risks / Trade-offs

- **[Risk] Microservice management complexity for local development**  
  → **Mitigation**: Modular `docker-compose.yml` with profiles (e.g. `compose --profile infra up`, `--profile core up`) so developers can run only the subset of services and dependencies needed for their current task.

- **[Risk] Schema drift in Kafka events across producer and consumer services**  
  → **Mitigation**: Explicit versioned event contracts (e.g. `PaymentSucceeded.v1`) and strict Pydantic envelope models. Breaking changes require a new version (e.g. `v2`) with backward compatibility support.

- **[Risk] Domain leakage into `libs/common`**  
  → **Mitigation**: Code review rules and automated linting/import boundaries prohibiting domain imports in `libs/common`.

- **[Risk] Duplicate event processing during consumer reconnections**  
  → **Mitigation**: Mandatory consumer idempotency via unique event IDs or dedicated idempotency tables before committing state changes.
