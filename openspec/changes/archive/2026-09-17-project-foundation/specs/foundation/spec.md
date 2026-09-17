## Purpose

Establishes the foundational architectural, technical, operational, and organizational standards for all microservices, databases, messaging mechanisms, deployment assets, and observability tools across the e-commerce backend platform.

## ADDED Requirements

### Requirement: Microservice Autonomy and Boundary Separation

Each business service MUST be an autonomous Python 3.x FastAPI application located under `services/<service-name>/` with its own isolated configuration, dependencies (`pyproject.toml`), container definitions (`Dockerfile`), database migrations, and test suites. Services SHALL NOT import business logic or domain modules from other services or shared libraries. Shared libraries (`libs/common/`) SHALL strictly contain infrastructure components (logging, correlation tracking, technical middleware, event envelope definitions).

#### Scenario: Service autonomy validation

- **WHEN** a service is built or run in isolation
- **THEN** it executes without importing domain code or business entities from any other service directory

### Requirement: Database per Service Isolation

Each microservice MUST own and manage its assigned database instance (PostgreSQL, Redis, Elasticsearch, MongoDB, or ClickHouse) and access it exclusively through its own application layer. Direct cross-service database queries, shared business tables, and cross-database foreign key constraints SHALL be strictly prohibited.

#### Scenario: Cross-database access prohibition

- **WHEN** a service requires data owned by another domain entity
- **THEN** it retrieves that data via synchronous REST API calls or asynchronous event consumption, never via direct SQL or database connection

### Requirement: REST API and Error Handling Standardization

All HTTP endpoints exposed by microservices or the API Gateway MUST adhere to RESTful naming conventions using plural nouns (`/products`, `/orders/{id}`) and structured JSON responses. Error responses MUST return standard HTTP status codes along with a JSON envelope containing an error code, user message, optional details, and the request ID.

#### Scenario: Standard error response format

- **WHEN** an HTTP request results in a client or business failure
- **THEN** the service returns an appropriate 4xx/5xx HTTP status code and a JSON body containing `error.code`, `error.message`, `error.details`, and `request_id`

### Requirement: Request and Correlation ID Propagation

Every HTTP request entering the API Gateway or microservices MUST incorporate an `X-Request-ID` header. If missing, a unique UUID SHALL be generated. For distributed operations crossing process boundaries via HTTP or Kafka, a `correlation_id` MUST be generated and propagated through request headers and message envelopes.

#### Scenario: Distributed correlation tracking

- **WHEN** a multi-service workflow or Kafka event processing chain is initiated
- **THEN** all log entries, HTTP sub-requests, and published Kafka events maintain the identical `correlation_id`

### Requirement: Standardized Kafka Event Envelope and Contracts

All asynchronous events published to Apache Kafka MUST adhere to a standardized versioned event envelope structure containing `event_id`, `event_type`, `event_version`, `occurred_at`, `producer`, `correlation_id`, and `payload`. Schema evolution MUST be versioned (e.g., `v1`, `v2`) to ensure backward compatibility for consumers.

#### Scenario: Kafka event publishing and consumption

- **WHEN** a domain service publishes an event to Kafka
- **THEN** the event envelope includes valid metadata and versioning parameters matching the registered event contract

### Requirement: Consumer Idempotency

All Kafka event consumers and async message handlers MUST be designed idempotently, ensuring that processing the same event ID or idempotency key multiple times produces no duplicate business side-effects.

#### Scenario: Duplicate message processing

- **WHEN** a consumer receives an identical Kafka event more than once
- **THEN** it identifies the event ID as previously processed and safely skips duplicate business processing

### Requirement: Outbox Pattern for Atomic Persistence and Messaging

Services requiring atomic updates to PostgreSQL and reliable event delivery to Apache Kafka MUST implement the Outbox Pattern. State changes and outbox records MUST be committed within the same database transaction before an independent relay process publishes events to Kafka.

#### Scenario: Failure during transaction and messaging

- **WHEN** a database transaction commits business state and inserts an outbox record
- **THEN** the outbox publisher reliably delivers the event to Kafka even if an application restart or network drop occurs after the DB commit

### Requirement: Structured JSON Logging and Secrets Protection

All microservices and gateway instances MUST output structured JSON logs including standard fields (`timestamp`, `level`, `service`, `message`, `request_id`, `correlation_id`). Passwords, API tokens, JWT secrets, and sensitive user data MUST be automatically redacted and NEVER written to logs.

#### Scenario: Log sanitization

- **WHEN** log records are generated during request execution or authentication
- **THEN** sensitive credentials are omitted or redacted, and all fields are serialized in JSON format

### Requirement: Test-Driven Strategy and Integration Isolation

Each microservice MUST maintain unit tests for domain logic isolated from external infrastructure, and integration tests using `Testcontainers` for real PostgreSQL, Redis, Kafka, MongoDB, Elasticsearch, or ClickHouse instances. Load testing MUST be provided via k6 scripts to validate concurrent execution constraints.

#### Scenario: Automated integration test execution

- **WHEN** integration test suites are executed
- **THEN** Testcontainers dynamically spins up required database and messaging instances without relying on pre-existing host infrastructure

### Requirement: Resiliency and Fault Tolerance (Timeouts and Circuit Breaker)

All inter-service HTTP calls, database queries, and external provider integrations MUST have explicitly configured timeouts. Infinite timeouts are strictly forbidden. A Circuit Breaker pattern MUST be used for synchronous integrations with potentially unstable external dependencies to prevent cascading failures.

#### Scenario: External provider timeout isolation

- **WHEN** the Payment Service attempts to contact an external payment gateway that is unresponsive
- **THEN** the request aborts after the configured timeout and the Circuit Breaker trips to prevent cascading failures without blocking the orchestrating service

### Requirement: Saga Orchestration for Distributed Transactions

Distributed workflows spanning multiple services (e.g., Checkout) MUST NOT use synchronous blocking HTTP chains (e.g., A -> B -> C -> D). They MUST be implemented using the Saga Pattern (Orchestration approach) to gracefully handle partial failures, duplicate events, and compensation logic.

#### Scenario: Distributed transaction compensation

- **WHEN** an order is created and stock is reserved, but the subsequent payment process fails
- **THEN** the Saga Orchestrator catches the failure event and triggers a compensating transaction to release the reserved stock and cancel the order

### Requirement: Specific Database Roles and Constraints

Services MUST use databases strictly according to their intended architectural roles: PostgreSQL as the primary source of truth, Redis for volatile state (cart, cache, rate limits), Elasticsearch strictly as a search projection (capable of reindexing from PostgreSQL), MongoDB exclusively for notification documents, and ClickHouse for OLAP.

#### Scenario: Analytics Data Retrieval

- **WHEN** the Analytics Service aggregates data to generate business reports
- **THEN** it queries ClickHouse using data ingested asynchronously from Kafka events, rather than executing direct SQL queries against operational PostgreSQL databases

### Requirement: API Gateway Boundaries and Responsibilities

The API Gateway acts as the single entry point and is strictly responsible for cross-cutting technical concerns: routing, request ID generation, authentication token validation, rate limiting, and CORS. It MUST NOT contain or enforce domain business logic.

#### Scenario: Business logic delegation

- **WHEN** a client submits a request to cancel an order via the API Gateway
- **THEN** the Gateway routes the request to the Order Service without evaluating business rules regarding the order's cancellation eligibility

### Requirement: Configuration and Secrets Management

Service configuration MUST be externalized using environment variables (e.g., via Pydantic Settings) and loaded at runtime. Hardcoding configurations (like `DATABASE_URL`) in application code is prohibited. Secrets MUST NOT be tracked in Git (`.env` must be in `.gitignore`), and production workloads MUST utilize Kubernetes Secrets.

#### Scenario: Database credential injection

- **WHEN** a service initializes its database connection pool in a production environment
- **THEN** it retrieves credentials securely from Kubernetes Secrets injected as environment variables, never from static code or Git-tracked `.env` files

### Requirement: Clean Architecture and Directory Structure

Microservices MUST adhere to a clear architectural boundary structure separating layers. The internal Python package structure MUST separate `api` (HTTP transport), `domain` (business entities), `application` (use cases), and `infrastructure` (DB repositories, external clients).

#### Scenario: Domain layer isolation

- **WHEN** the business logic inside the `domain` or `application` layer is executed or unit-tested
- **THEN** it operates completely independently without importing FastAPI components, HTTP request objects, or database-specific ORM models

### Requirement: Deployment and Infrastructure Orchestration

Deployment mechanisms MUST be strictly separated by environment. Docker Compose is reserved EXCLUSIVELY for local development. Kubernetes is the target production-like platform, utilizing Helm for parameterized deployments (`dev`, `staging`, `prod`) and immutable image tags. Ansible is restricted to VM infrastructure provisioning. Docker images MUST utilize multi-stage builds and run as non-root users.

#### Scenario: Production workload orchestration

- **WHEN** a service is deployed to the staging or production environment
- **THEN** it is managed by Kubernetes via Helm charts utilizing parameterized environment values and immutable Git SHA tags, rather than Docker Compose

### Requirement: CI/CD Pipeline Standardization

All services MUST integrate with a standardized Jenkins CI/CD pipeline. Production deployments MUST NEVER depend on floating tags like `latest`.

#### Scenario: Automated delivery pipeline execution

- **WHEN** code is pushed to the repository
- **THEN** the CI/CD pipeline automatically executes Linting, Unit/Integration Tests, Trivy Security Scans, builds a multi-stage Docker image, tags it with an immutable Git SHA, and deploys it via Helm

### Requirement: Observability Stack and Business Metrics

The platform MUST integrate with Prometheus and Grafana for metrics aggregation, and OpenTelemetry and Jaeger for distributed tracing. Beyond technical metrics, services MUST expose business metrics (e.g., `orders_completed_total`, `stock_reservation_failed_total`).

#### Scenario: Distributed tracing context propagation

- **WHEN** a user request spans across the API Gateway, Order Service, Kafka, and Payment Service
- **THEN** the identical `correlation_id` is propagated across HTTP and Kafka boundaries, resulting in a unified visual trace in Jaeger

### Requirement: Health Checks and Graceful Shutdown

Every HTTP service MUST expose standard `/health/live` and `/health/ready` endpoints. Services MUST implement graceful shutdown procedures to ensure zero-downtime rolling updates in Kubernetes.

#### Scenario: Kubernetes pod termination

- **WHEN** Kubernetes sends a SIGTERM signal to stop a service pod during a rolling update
- **THEN** the service stops accepting new traffic, finishes ongoing requests, safely closes active database and Kafka connections, and then exits

### Requirement: 20 Architectural Invariants Foundation

The foundation MUST establish a strict set of 20 architectural invariants (e.g., Database per Service, idempotent consumers, Outbox pattern, Saga, non-root containers, secrets out of Git). These rules serve as the constitution for all future microservices.

#### Scenario: Subsequent specification validation

- **WHEN** a new bounded context specification (e.g., `01-auth-service`) is defined and implemented
- **THEN** it strictly inherits and complies with all foundation invariants without redefining database isolation, messaging constraints, or deployment paradigms
