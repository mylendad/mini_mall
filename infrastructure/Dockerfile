FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache .

FROM python:3.12-slim AS runtime

WORKDIR /app

RUN useradd -u 10001 appuser && chown -R appuser:appuser /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

USER appuser

EXPOSE 8000

CMD ["uvicorn", "services.template.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
