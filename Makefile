# PentestGPT Makefile
# Usage: make [target]

.PHONY: help install test test-cov test-verbose lint format typecheck clean build
.PHONY: ci ci-quick
.PHONY: docker-build docker-login docker-auth-status docker-shell docker-run docker-down docker-nuke
.PHONY: docker-bench-agent-quick bench-agent-quick docker-bench-bestof3 bench-bestof3
.PHONY: docker-bench-set bench-set docker-bench-set-list bench-set-list

# Default target
help:
	@echo "PentestGPT Agent Commands"
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
	@echo "  make docker-run TARGET=… BACKEND=… MODEL=… GOAL=…   Run the framework against a target"
	@echo "  make docker-shell        Interactive shell in the tool container"
	@echo "  make docker-nuke         Remove login volumes (forces re-login)"
	@echo ""
	@echo "Benchmarks:"
	@echo "  make docker-bench-agent-quick   Default local pentestgpt_agent benchmark smoke"
	@echo "  make docker-bench-bestof3       Full best-of-three single/framework benchmark"

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
	uv run pytest tests/ -v --cov=pentestgpt_agent --cov=unified_agent --cov-report=term-missing --cov-report=html

test-verbose:
	uv run pytest tests/ -vvs

# Test by category
test-unit:
	uv run pytest tests/unit/ tests/test_*.py -v

test-integration:
	uv run pytest tests/test_framework_loop.py tests/test_roles.py -v

test-fast:
	uv run pytest tests/ -v -m "not slow"

# Run specific test files
test-session:
	uv run pytest tests/test_ledger.py -v

test-events:
	uv run pytest tests/test_framework_loop.py -v

test-controller:
	uv run pytest tests/test_framework_loop.py tests/test_roles.py -v

test-backend:
	uv run pytest tests/test_claude_backend.py tests/test_codex_backend.py -v

test-config:
	uv run pytest tests/test_roles.py -v

# ============================================================================
# Code Quality
# ============================================================================

lint:
	uv run ruff check pentestgpt_agent/ unified_agent/ pentestgpt_legacy/ tests/

lint-fix:
	uv run ruff check --fix pentestgpt_agent/ unified_agent/ pentestgpt_legacy/ tests/

format:
	uv run ruff format pentestgpt_agent/ unified_agent/ pentestgpt_legacy/ tests/

format-check:
	uv run ruff format --check pentestgpt_agent/ unified_agent/ pentestgpt_legacy/ tests/

typecheck:
	uv run mypy pentestgpt_agent/

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
	uv run ruff check pentestgpt_agent/ unified_agent/ pentestgpt_legacy/ tests/
	@echo ""
	@echo "[2/5] Format check (ruff format --check)..."
	uv run ruff format --check pentestgpt_agent/ unified_agent/ pentestgpt_legacy/ tests/
	@echo ""
	@echo "[3/5] Type check (mypy)..."
	uv run mypy pentestgpt_agent/
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
	uv run ruff check pentestgpt_agent/ unified_agent/ pentestgpt_legacy/ tests/
	@echo ""
	@echo "[2/4] Format check (ruff format --check)..."
	uv run ruff format --check pentestgpt_agent/ unified_agent/ pentestgpt_legacy/ tests/
	@echo ""
	@echo "[3/4] Type check (mypy)..."
	uv run mypy pentestgpt_agent/
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
	@test -n "$(TARGET)" || (echo "Set TARGET=... (e.g. http://127.0.0.1:8000)"; exit 1)
	uv run pentestgpt-agent --goal "$(or $(GOAL),Assess the target for exploitable vulnerabilities and capture any CTF flag.)" --target "$(TARGET)" --backend "$(BACKEND)" $(if $(MODEL),--model "$(MODEL)",)

# Run in debug mode
run-debug:
	@test -n "$(TARGET)" || (echo "Set TARGET=... (e.g. http://127.0.0.1:8000)"; exit 1)
	uv run python -m pentestgpt_agent --goal "$(or $(GOAL),Assess the target for exploitable vulnerabilities and capture any CTF flag.)" --target "$(TARGET)" --backend "$(BACKEND)" $(if $(MODEL),--model "$(MODEL)",)

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
# Run knobs (override on the CLI): TARGET, BACKEND, MODEL, GOAL
BACKEND ?= claude
MODEL   ?=
GOAL    ?= Capture the CTF flag for this authorized benchmark target.

# Default local verification for pentestgpt_agent changes.
# Override knobs:
#   AGENT_BENCH_TARGETS=XBEN-080-24
#   AGENT_BENCH_COMBOS=claude-sonnet
#   AGENT_BENCH_CONCURRENCY=1
#   AGENT_BENCH_EXECUTOR_CONCURRENCY=2
#   AGENT_BENCH_TIMEOUT=1200
AGENT_BENCH_TARGETS              ?= XBEN-080-24
AGENT_BENCH_COMBOS               ?= claude-sonnet
AGENT_BENCH_CONCURRENCY          ?= 1
AGENT_BENCH_EXECUTOR_CONCURRENCY ?= 2
AGENT_BENCH_TIMEOUT              ?= 1200
AGENT_BENCH_ATTEMPT              ?= $(shell date +%Y%m%d%H%M%S)
AGENT_BENCH_ATTEMPTS             ?= 1
AGENT_BENCH_MAX_CODEX            ?= 1
AGENT_BENCH_OUT                  ?= docker_framework_quick.jsonl

# Final best-of-three comparison suite.
# Override knobs:
#   BOF3_RUN_ID=20260629_190000
#   BOF3_SKIP_CANARY=1
#   BOF3_DRY_RUN=1
BOF3_RUN_ID                         ?= $(shell date +%Y%m%d_%H%M%S)
BOF3_BENCHMARKS                     ?= XBEN-001-24,XBEN-030-24,XBEN-057-24,XBEN-068-24,XBEN-075-24,XBEN-079-24,XBEN-080-24,XBEN-082-24,XBEN-097-24,XBEN-101-24
BOF3_COMBOS                         ?= claude-opus,claude-sonnet,codex-gpt-5.5,codex-gpt-5.4-mini
BOF3_TIMEOUT                        ?= 2400
BOF3_CONCURRENCY                    ?= 2
BOF3_MAX_CODEX                      ?= 1
BOF3_ATTEMPT                        ?= 1
BOF3_ATTEMPTS                       ?= 3
BOF3_FRAMEWORK_EXECUTOR_CONCURRENCY ?= 2
BOF3_SOURCE_ROOT                    ?= ../..
BOF3_CANARY_BENCHMARKS              ?= XBEN-068-24,XBEN-080-24
BOF3_CANARY_SINGLE_COMBOS           ?= claude-sonnet,codex-gpt-5.5
BOF3_CANARY_FRAMEWORK_COMBOS        ?= claude-sonnet
BOF3_CANARY_TIMEOUT                 ?= 1200
BOF3_SKIP_CANARY_FLAG               = $(if $(filter 1 true yes,$(BOF3_SKIP_CANARY)),--skip-canary,)
BOF3_DRY_RUN_FLAG                   = $(if $(filter 1 true yes,$(BOF3_DRY_RUN)),--dry-run,)

# Toggleable named benchmark sets (benchmark/pilot/benchmark_sets.json).
# `bench_set.py` runs only the challenges whose `enabled` flag is on, and
# auto-picks parallelism unless BENCH_SET_CONCURRENCY is a number.
# Override knobs:
#   BENCH_SET=hard-open BENCH_SET_VARIANT=framework|single|both
#   BENCH_SET_CONCURRENCY=auto|N  BENCH_SET_COMBOS=claude-sonnet
#   BENCH_SET_DRY_RUN=1
BENCH_SET                ?= hard-open
BENCH_SET_VARIANT        ?= framework
BENCH_SET_CONCURRENCY    ?= auto
BENCH_SET_COMBOS         ?= claude-opus,claude-sonnet,codex-gpt-5.5,codex-gpt-5.4-mini
BENCH_SET_TIMEOUT        ?= 2400
BENCH_SET_ATTEMPT        ?= 1
BENCH_SET_ATTEMPTS       ?= 1
BENCH_SET_MAX_CODEX      ?= 1
BENCH_SET_EXECUTOR_CONCURRENCY ?= 2
BENCH_SET_XBEN_ROOT      ?= /Users/gelei/papers/cochise/xbow-benchmarks/benchmarks
BENCH_SET_DRY_RUN_FLAG   = $(if $(filter 1 true yes,$(BENCH_SET_DRY_RUN)),--dry-run,)

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

# Run the framework against a target:
#   make docker-run TARGET=http://127.0.0.1:8000 BACKEND=codex MODEL=gpt-5.5
docker-run:
	@test -n "$(TARGET)" || (echo "Set TARGET=... (e.g. http://host:port)"; exit 1)
	docker run --rm $(DOCKER_RUN_MOUNTS) -e PENTESTGPT_AUTH_MODE=manual \
		$(DOCKER_IMAGE) pentestgpt-agent --goal "$(GOAL)" --target "$(TARGET)" \
		--backend "$(BACKEND)" $(if $(MODEL),--model "$(MODEL)",)

# Default local benchmark smoke for pentestgpt_agent development.
# Assumes `make docker-build` and `make docker-login` have already succeeded.
docker-bench-agent-quick:
	@echo "Running pentestgpt_agent quick benchmark:"
	@echo "  targets=$(AGENT_BENCH_TARGETS)"
	@echo "  combos=$(AGENT_BENCH_COMBOS)"
	@echo "  attempt=$(AGENT_BENCH_ATTEMPT)"
	@echo "  concurrency=$(AGENT_BENCH_CONCURRENCY), executor_concurrency=$(AGENT_BENCH_EXECUTOR_CONCURRENCY)"
	cd benchmark/pilot && PILOT_COMBOS="$(AGENT_BENCH_COMBOS)" uv run python run_docker_bench.py \
		--variant framework \
		--image "$(DOCKER_IMAGE)" \
		--source-root ../.. \
		--benchmarks "$(AGENT_BENCH_TARGETS)" \
		--timeout "$(AGENT_BENCH_TIMEOUT)" \
		--concurrency "$(AGENT_BENCH_CONCURRENCY)" \
		--framework-executor-concurrency "$(AGENT_BENCH_EXECUTOR_CONCURRENCY)" \
		--attempt "$(AGENT_BENCH_ATTEMPT)" \
		--attempts "$(AGENT_BENCH_ATTEMPTS)" \
		--max-codex "$(AGENT_BENCH_MAX_CODEX)" \
		--out "$(AGENT_BENCH_OUT)"
	@echo "Results: benchmark/pilot/$(AGENT_BENCH_OUT)"

bench-agent-quick: docker-bench-agent-quick

# Full final comparison: single-agent vs pentestgpt_agent.
# Produces timestamped docker_bof3_<run-id>_*.jsonl files and
# DOCKER_BEST_OF_3_<run-id>.md under benchmark/pilot/.
docker-bench-bestof3:
	cd benchmark/pilot && uv run python run_bestof3_suite.py \
		--run-id "$(BOF3_RUN_ID)" \
		--image "$(DOCKER_IMAGE)" \
		--source-root "$(BOF3_SOURCE_ROOT)" \
		--benchmarks "$(BOF3_BENCHMARKS)" \
		--combos "$(BOF3_COMBOS)" \
		--timeout "$(BOF3_TIMEOUT)" \
		--concurrency "$(BOF3_CONCURRENCY)" \
		--max-codex "$(BOF3_MAX_CODEX)" \
		--attempt "$(BOF3_ATTEMPT)" \
		--attempts "$(BOF3_ATTEMPTS)" \
		--framework-executor-concurrency "$(BOF3_FRAMEWORK_EXECUTOR_CONCURRENCY)" \
		--canary-benchmarks "$(BOF3_CANARY_BENCHMARKS)" \
		--canary-single-combos "$(BOF3_CANARY_SINGLE_COMBOS)" \
		--canary-framework-combos "$(BOF3_CANARY_FRAMEWORK_COMBOS)" \
		--canary-timeout "$(BOF3_CANARY_TIMEOUT)" $(BOF3_SKIP_CANARY_FLAG) $(BOF3_DRY_RUN_FLAG)

bench-bestof3: docker-bench-bestof3

# Show a toggleable benchmark set and its on/off state.
docker-bench-set-list:
	cd benchmark/pilot && uv run python bench_set.py list --set "$(BENCH_SET)"

bench-set-list: docker-bench-set-list

# Run only the ENABLED challenges of a named set. Docker (build -> up ->
# discover -> run tool image -> score -> teardown) happens inside the runner.
# BENCH_SET_CONCURRENCY=auto lets the tool suggest parallelism; pass a number to fix it.
docker-bench-set:
	cd benchmark/pilot && XBEN_ROOT="$(BENCH_SET_XBEN_ROOT)" uv run python bench_set.py run \
		--set "$(BENCH_SET)" \
		--variant "$(BENCH_SET_VARIANT)" \
		--concurrency "$(BENCH_SET_CONCURRENCY)" \
		--combos "$(BENCH_SET_COMBOS)" \
		--image "$(DOCKER_IMAGE)" \
		--source-root ../.. \
		--timeout "$(BENCH_SET_TIMEOUT)" \
		--attempt "$(BENCH_SET_ATTEMPT)" \
		--attempts "$(BENCH_SET_ATTEMPTS)" \
		--max-codex "$(BENCH_SET_MAX_CODEX)" \
		--framework-executor-concurrency "$(BENCH_SET_EXECUTOR_CONCURRENCY)" $(BENCH_SET_DRY_RUN_FLAG)

bench-set: docker-bench-set

# Stop/remove the compose container but KEEP the login volumes (stay logged in)
docker-down:
	docker compose down

# Remove the persisted login volumes (forces a fresh `make docker-login`)
docker-nuke:
	-docker volume rm $(CLAUDE_VOL) $(CODEX_VOL)
