# syntax=docker/dockerfile:1

# Build context: repository root (docker build . )
# The auth service treats `common` as a normal installed library.

FROM python:3.12-slim AS builder

WORKDIR /build

# Build the shared library wheel first.
COPY libs/common ./libs/common
RUN pip wheel --no-cache-dir --no-deps --wheel-dir=/wheels ./libs/common

# Build the auth service wheel.
COPY services/auth ./services/auth
WORKDIR /build/services/auth
RUN pip wheel --no-cache-dir --no-deps --wheel-dir=/wheels .

FROM python:3.12-slim

WORKDIR /app/services/auth

RUN useradd -m -u 1000 appuser

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]