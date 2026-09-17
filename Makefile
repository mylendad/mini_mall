.PHONY: help install lint test clean docs

help:
	@echo "Available commands:"
	@echo "  make install   - Install dependencies using uv or pip"
	@echo "  make lint      - Run linters (ruff)"
	@echo "  make test      - Run test suite"
	@echo "  make docs      - Generate API docs from docstrings (pdoc)"
	@echo "  make clean     - Clean up cache and build artifacts"

install:
	pip install -e .[dev]

lint:
	ruff check .

test:
	pytest

docs:
	.venv/bin/pdoc common --output-dir docs/api/common
	PYTHONPATH=services/auth .venv/bin/pdoc app.api.auth app.config app.database app.main app.models.user app.repositories.auth_repo app.schemas.auth app.services.security app.services.token --output-dir docs/api/auth

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete