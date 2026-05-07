.PHONY: help install dev test test-ci test-cov test-hooks lint format format-fix format-check \
        type-check sloppylint ci ci-fast fix setup-hooks pre-commit clean version build run

help:
	@echo "give-back - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make venv        - Create virtual environment (requires uv)"
	@echo "  make install     - Install runtime dependencies"
	@echo "  make dev         - Install dev dependencies + auto-install git hooks"
	@echo "  make setup-hooks - Re-install the git pre-commit/pre-push hooks"
	@echo ""
	@echo "Development:"
	@echo "  make run         - Run give-back (ARGS, e.g. make run ARGS='assess pallets/flask')"
	@echo "  make test        - Run tests"
	@echo "  make test-cov    - Run tests with coverage"
	@echo "  make test-hooks  - Smoke test the git hooks infrastructure"
	@echo "  make lint        - Run linter (ruff check)"
	@echo "  make format      - Format code (ruff format, mutates files)"
	@echo "  make format-check- Check formatting (ruff format --check, read-only)"
	@echo "  make type-check  - Run mypy in strict mode"
	@echo "  make sloppylint  - Run sloppylint regression gate"
	@echo ""
	@echo "Quality gates:"
	@echo "  make ci          - Run all CI-equivalent checks locally (READ-ONLY)"
	@echo "  make ci-fast     - Fast format-check only (used by the git pre-commit hook)"
	@echo "  make fix         - Auto-format + auto-fix ruff lint issues"
	@echo "  make pre-commit  - Alias for 'make ci' (backward compat)"
	@echo ""
	@echo "Build & Release:"
	@echo "  make version     - Show current version"
	@echo "  make build       - Build package"
	@echo "  make clean       - Clean build artifacts"

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
	@bash scripts/setup-hooks.sh --quiet

run:
	uv run give-back $(ARGS)

test:
	uv run pytest tests/ -v

# Coverage-enabled test run used by CI and `make ci`.
# Separate from `make test` to keep local iteration fast.
test-ci:
	uv run pytest tests/ -v --cov=src/give_back --cov-report=term

test-cov:
	uv run pytest tests/ -v --cov=src/give_back --cov-report=html --cov-report=term

test-hooks:
	@bash tests/test_hooks_smoke.sh

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

format-fix:
	uv run ruff check src/ tests/ --fix

format-check:
	uv run ruff format --check src/ tests/

type-check:
	uv run mypy src/

sloppylint:
	uv run --with sloppylint sloppylint --max-score 151 src/

# CI-equivalent checks. READ-ONLY — does not mutate files.
# This target mirrors .github/workflows/ci.yml exactly. Run it before
# pushing to catch everything CI will catch, without the network round-trip.
ci: lint format-check type-check test-ci sloppylint
	@echo "CI-equivalent checks passed."

# Fast format-check only. Used by the git pre-commit hook to keep
# per-commit friction minimal. Target: well under 1 second warm.
ci-fast: format-check
	@echo "Fast format check passed."

# Auto-fix: formats + applies ruff auto-fixable lint rules.
# Use this after 'make ci' fails on format or auto-fixable lint issues.
fix:
	uv run ruff format src/ tests/
	uv run ruff check src/ tests/ --fix
	@echo "Auto-fixed formatting and auto-fixable lint issues. Re-run 'make ci' to verify."

# Install the tracked .githooks/ directory as the active git hooks path.
# Idempotent. Warns if core.hooksPath is already set to something else.
setup-hooks:
	@bash scripts/setup-hooks.sh

# Backward-compat alias. 'make pre-commit' → 'make ci'.
# Kept for muscle memory and existing doc references.
pre-commit: ci

version:
	@echo "Git tag: $$(git describe --tags --always 2>/dev/null || echo 'no tags')"

build:
	uv run --with build python -m build

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage htmlcov/ src/give_back/_version.py
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
