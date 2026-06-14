# PentestGPT Makefile
# Usage: make [target]

.PHONY: help install test test-cov test-verbose lint format typecheck clean build
.PHONY: ci ci-quick
.PHONY: docker-build docker-login docker-auth-status docker-shell docker-run docker-down docker-nuke

# Default target
help:
	@echo "PentestGPT Commands"
	@echo "==================="
	@echo ""
	@echo "Setup:"
	@echo "  make install     Install dependencies (uv sync)"
	@echo ""
	@echo "Development:"
	@echo "  make test         Run all tests"
	@echo "  make lint         Run linter (ruff)"
	@echo "  make format       Format code (ruff)"
	@echo "  make typecheck    Run type checker (mypy)"
	@echo "  make check        Run all checks (lint + typecheck)"
	@echo "  make ci           Run full CI simulation (lint, format, typecheck, test, build)"
	@echo "  make ci-quick     Run quick CI (skip build step)"
	@echo "  make clean        Clean build artifacts"
	@echo ""
	@echo "Docker (the tool, with persistent Claude + Codex login):"
	@echo "  make docker-build        Build the tool image"
	@echo "  make docker-login        ONE-TIME: log in to Claude + Codex (persists to volumes)"
	@echo "  make docker-auth-status  Check both CLIs are logged in (ROUNDTRIP=1 for live check)"
	@echo "  make docker-run TARGET=… BACKEND=… MODEL=… MODE=…   Run the pipeline against a target"
	@echo "  make docker-shell        Interactive shell in the tool container"
	@echo "  make docker-nuke         Remove login volumes (forces re-login)"

# ============================================================================
# Setup
# ============================================================================

install:
	uv sync

# ============================================================================
# Testing
# ============================================================================

test:
	uv run pytest tests/ -v

test-all:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov=pentestgpt --cov-report=term-missing --cov-report=html

test-verbose:
	uv run pytest tests/ -vvs

# Test by category
test-unit:
	uv run pytest tests/unit/ -v

test-integration:
	uv run pytest tests/integration/ -v

test-fast:
	uv run pytest tests/ -v -m "not slow"

# Run specific test files
test-session:
	uv run pytest tests/unit/test_session.py -v

test-events:
	uv run pytest tests/unit/test_events.py -v

test-controller:
	uv run pytest tests/integration/test_controller.py -v

test-backend:
	uv run pytest tests/unit/test_backend_interface.py -v

test-config:
	uv run pytest tests/unit/test_config.py -v

# ============================================================================
# Code Quality
# ============================================================================

lint:
	uv run ruff check pentestgpt/ pentestgpt_legacy/ tests/

lint-fix:
	uv run ruff check --fix pentestgpt/ pentestgpt_legacy/ tests/

format:
	uv run ruff format pentestgpt/ pentestgpt_legacy/ tests/

format-check:
	uv run ruff format --check pentestgpt/ pentestgpt_legacy/ tests/

typecheck:
	uv run mypy pentestgpt/

check: lint typecheck
	@echo "All checks passed!"

# ============================================================================
# CI Simulation (End-to-End)
# ============================================================================

# Full CI simulation - mirrors GitHub Actions workflow exactly
ci:
	@echo "=========================================="
	@echo "Running full CI simulation..."
	@echo "=========================================="
	@echo ""
	@echo "[1/5] Lint check (ruff check)..."
	uv run ruff check pentestgpt/ pentestgpt_legacy/ tests/
	@echo ""
	@echo "[2/5] Format check (ruff format --check)..."
	uv run ruff format --check pentestgpt/ pentestgpt_legacy/ tests/
	@echo ""
	@echo "[3/5] Type check (mypy)..."
	uv run mypy pentestgpt/
	@echo ""
	@echo "[4/5] Running tests..."
	uv run pytest tests/ -v
	@echo ""
	@echo "[5/5] Building package..."
	uv build
	@echo ""
	@echo "=========================================="
	@echo "CI simulation completed successfully!"
	@echo "=========================================="

# Quick CI - skip build step (faster iteration)
ci-quick:
	@echo "=========================================="
	@echo "Running quick CI simulation..."
	@echo "=========================================="
	@echo ""
	@echo "[1/4] Lint check (ruff check)..."
	uv run ruff check pentestgpt/ pentestgpt_legacy/ tests/
	@echo ""
	@echo "[2/4] Format check (ruff format --check)..."
	uv run ruff format --check pentestgpt/ pentestgpt_legacy/ tests/
	@echo ""
	@echo "[3/4] Type check (mypy)..."
	uv run mypy pentestgpt/
	@echo ""
	@echo "[4/4] Running tests..."
	uv run pytest tests/ -v
	@echo ""
	@echo "=========================================="
	@echo "Quick CI simulation completed successfully!"
	@echo "=========================================="

# ============================================================================
# Build
# ============================================================================

build:
	uv build

clean:
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# ============================================================================
# Local Development
# ============================================================================

# Run locally
run:
	uv run pentestgpt --target example.com

# Run in debug mode
run-debug:
	uv run pentestgpt --target example.com --debug

# Watch for changes and run tests
watch:
	uv run ptw tests/ -- -v

# ============================================================================
# Docker (the tool, with persistent Claude + Codex login)
# ============================================================================

DOCKER_IMAGE  ?= pentestgpt:latest
CLAUDE_VOL    ?= pentestgpt-claude
CODEX_VOL     ?= pentestgpt-codex
# Mount the persisted login volumes + a host workspace into a run.
DOCKER_AUTH_MOUNTS = -v $(CLAUDE_VOL):/home/pentester/.claude -v $(CODEX_VOL):/home/pentester/.codex
DOCKER_RUN_MOUNTS  = $(DOCKER_AUTH_MOUNTS) -v $(PWD)/workspace:/workspace
# Run knobs (override on the CLI): TARGET, BACKEND, MODEL, MODE, INSTRUCTION
BACKEND ?= claude
MODEL   ?=
MODE    ?= ctf

# Build the tool image
docker-build:
	docker build -t $(DOCKER_IMAGE) .

# ONE-TIME: log in to Claude + Codex; persists into named volumes (no re-login after)
docker-login:
	./scripts/docker-login.sh

# Report whether both CLIs are logged in (add ROUNDTRIP=1 for a live 1-token check)
docker-auth-status:
	docker run --rm $(DOCKER_AUTH_MOUNTS) --entrypoint bash $(DOCKER_IMAGE) \
		-lc '/home/pentester/docker-auth-status.sh $(if $(ROUNDTRIP),--roundtrip,)'

# Interactive shell in the tool container (login volumes attached)
docker-shell:
	docker run -it --rm $(DOCKER_RUN_MOUNTS) -e PENTESTGPT_AUTH_MODE=manual $(DOCKER_IMAGE)

# Run the pipeline against a target:
#   make docker-run TARGET=http://127.0.0.1:8000 BACKEND=codex MODEL=gpt-5.5 MODE=ctf
docker-run:
	@test -n "$(TARGET)" || (echo "Set TARGET=... (e.g. http://host:port)"; exit 1)
	docker run --rm $(DOCKER_RUN_MOUNTS) -e PENTESTGPT_AUTH_MODE=manual \
		$(DOCKER_IMAGE) pentestgpt --target $(TARGET) --backend $(BACKEND) \
		$(if $(MODEL),--model $(MODEL),) --mode $(MODE) --no-telemetry \
		$(if $(INSTRUCTION),--instruction "$(INSTRUCTION)",)

# Stop/remove the compose container but KEEP the login volumes (stay logged in)
docker-down:
	docker compose down

# Remove the persisted login volumes (forces a fresh `make docker-login`)
docker-nuke:
	-docker volume rm $(CLAUDE_VOL) $(CODEX_VOL)
