.PHONY: help install dev test lint format clean pre-commit version

help:
	@echo "give-back - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make venv      - Create virtual environment (requires uv)"
	@echo "  make install   - Install dependencies"
	@echo "  make dev       - Install dev dependencies"
	@echo ""
	@echo "Development:"
	@echo "  make run       - Run give-back (pass ARGS, e.g. make run ARGS='assess pallets/flask')"
	@echo "  make test      - Run tests"
	@echo "  make test-cov  - Run tests with coverage"
	@echo "  make lint      - Run linter"
	@echo "  make format    - Format code"
	@echo ""
	@echo "Build & Release:"
	@echo "  make version   - Show current version"
	@echo "  make build     - Build package"
	@echo "  make clean     - Clean build artifacts"
	@echo ""
	@echo "Quality:"
	@echo "  make pre-commit - Format + lint + test"

venv:
	@command -v uv >/dev/null 2>&1 || { echo "Error: uv is not installed."; exit 1; }
	@if [ ! -d ".venv" ]; then \
		echo "Creating virtual environment..."; \
		uv sync --group dev; \
	else \
		echo "Virtual environment already exists."; \
	fi

install:
	uv sync

dev: install
	uv sync --group dev

run:
	uv run give-back $(ARGS)

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov=give_back --cov-report=html --cov-report=term

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

format-fix:
	uv run ruff check src/ tests/ --fix

format-check:
	uv run ruff format --check src/ tests/

version:
	@echo "Git tag: $$(git describe --tags --always 2>/dev/null || echo 'no tags')"

build:
	uv run --with build python -m build

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage htmlcov/ src/give_back/_version.py
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

pre-commit: format lint test
	@echo "Pre-commit checks passed."
