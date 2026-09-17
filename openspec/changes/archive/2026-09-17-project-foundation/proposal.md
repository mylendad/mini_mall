## Why

Establish the architectural, technical, and organizational foundation for a production-like e-commerce backend platform. Setting uniform rules for microservices, API contracts, database ownership, event streaming, observability, testing, and containerization up front prevents ad-hoc architectural drift and enables seamless integration of future services (Auth, Catalog, Cart, Inventory, Order, Payment, Delivery, Notification, Analytics).

## What Changes

- Establish fundamental architectural rules: microservice autonomy, Database-per-Service, single Source of Truth per domain entity, and strict separation of business logic from infrastructure code.
- Define service boundaries and tech stack constraints (Python 3.x, FastAPI, Pydantic, PostgreSQL, Redis, Elasticsearch, MongoDB, ClickHouse, Apache Kafka).
- Standardize communication patterns: REST API conventions for synchronous requests, and event-driven architecture using Kafka for asynchronous events.
- Mandate standardized Kafka Event Envelope contracts, event versioning, consumer idempotency, Outbox Pattern, and Saga Orchestration for distributed transactions.
- Set rules for environment configuration, secrets management, non-root Docker builds, Docker Compose local development, Kubernetes deployments with Helm, Ansible infrastructure provisioning, and Jenkins CI/CD pipelines.
- Standardize testing strategies (Unit, Integration with Testcontainers, Contract, Load with k6) and Observability standards (Structured JSON logging, Request/Correlation ID propagation, OpenTelemetry/Jaeger distributed tracing, Prometheus metrics, and Grafana dashboards).
- Define the API Gateway as a strict technical proxy (routing, rate limiting, token validation) containing zero domain business logic.
- Establish a security baseline ensuring non-root container execution, Trivy dependency scanning, and strict secrets management via Kubernetes Secrets (no secrets in Git).

## Capabilities

### New Capabilities

- `foundation`: Architectural constraints, service inventory, data storage guidelines, API contracts, messaging standards, testing rules, and deployment baseline for the e-commerce microservice platform.

### Modified Capabilities

- None

## Impact

- All future microservices (`services/*`), API Gateway (`gateway/`), shared libraries (`libs/common/`), and infrastructure manifests (`infrastructure/`) must strictly adhere to this architectural baseline.
- Establishes project repository structure, CI/CD pipeline stages, and local development configurations.
