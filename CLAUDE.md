# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PentestGPT is an AI-powered autonomous penetration testing agent with a terminal user interface (TUI). It uses an agentic pipeline to solve CTF challenges, Hack The Box machines, and authorized security assessments.

**Published at USENIX Security 2024**: [Paper](https://www.usenix.org/conference/usenixsecurity24/presentation/deng)

**Stack:** Python 3.12+, uv, Docker (Ubuntu 24.04), Textual (TUI), Rich (CLI), Claude Agent SDK

## Common Commands

```bash
# Development
uv sync                           # Install dependencies
uv run pentestgpt --target X      # Run locally
uv run pentestgpt --target X --raw  # Streaming output, no TUI (debugging)
uv run pentestgpt --resume        # Resume latest session

# Testing
make test                         # Run all tests (excludes docker/)
make test-cov                     # Tests with coverage report
make test-fast                    # Skip slow and docker tests
uv run pytest tests/unit/test_session.py -v        # Single file
uv run pytest tests/unit/test_session.py::test_name -v  # Single test

# Code Quality
make lint                         # ruff check
make format                       # ruff format
make typecheck                    # mypy (strict mode)
make check                        # lint + typecheck

# CI Simulation (mirrors GitHub Actions)
make ci-quick                     # lint + format-check + typecheck + tests
make ci                           # ci-quick + build

# Docker Workflow
make install                      # uv sync + build Docker image
make connect                      # Connect to container (main usage)
make stop                         # Stop container
make clean-docker                 # Remove everything including config
```

## Architecture

### Two-Layer Agent Design

The agent has two layers — use `AgentController` (high-level) for new code:

- **`PentestAgent`** (`core/agent.py`): Lower-level wrapper around Claude SDK. Handles flag detection, debug logging to `/workspace/pentestgpt-debug.log`.
- **`AgentController`** (`core/controller.py`): High-level orchestrator with 5-state lifecycle (IDLE→RUNNING→PAUSED→COMPLETED→ERROR), session persistence, event bus integration. Pause/resume happens at message boundaries for clean instruction injection.

### Core Layer (`pentestgpt/core/`)
- **backend.py** - `AgentBackend` abstract interface + `ClaudeCodeBackend` implementation. Framework-agnostic: messages abstracted as `AgentMessage` objects.
- **events.py** - `EventBus`: Thread-safe singleton pub/sub. Events: `STATE_CHANGED`, `MESSAGE`, `TOOL`, `FLAG_FOUND`, `USER_INPUT`.
- **session.py** - `SessionStore`: JSON persistence in `~/.pentestgpt/sessions/`. Tracks target, flags, cost, backend session ID for SDK resumption.
- **config.py** - `PentestGPTConfig`: Pydantic settings loaded from `.env`. Key defaults: model=`claude-sonnet-4-5-20250929`, max_iterations=300, permission_mode=`bypassPermissions`.
- **langfuse.py** - Observability via Langfuse. Deferred span creation (only on first tool execution). All errors caught silently to prevent output pollution.

### Interface Layer (`pentestgpt/interface/`)
- **main.py** - CLI entry point. Modes: TUI (default), CLI (`--non-interactive`), Raw (`--raw`), Debug (`--debug`).
- **tui.py** - Textual app. Controls: F1 help, Ctrl+P pause, Ctrl+Q quit.
- **components/** - ActivityFeed, SplashScreen, tool-specific Renderers.

### System Prompts (`pentestgpt/prompts/`)
- **pentesting.py** - `CTF_SYSTEM_PROMPT`: Detailed CTF methodology, flag formats, persistence directives.

## Key Patterns

- **Event-Driven Decoupling**: TUI and Langfuse subscribe to EventBus; agent emits events. No direct coupling between layers.
- **Singletons**: `EventBus.get()`, `get_global_tracer()` (local activity tracking for TUI, not telemetry).
- **Abstract Backend**: `AgentBackend` interface allows swapping LLM backends (currently only `ClaudeCodeBackend`).
- **Flag Detection**: Regex patterns in both `agent.py` and `controller.py` match `flag{}`, `HTB{}`, `CTF{}`, generic `Name{}`, and 32-char hex.

## Code Style

- **Line length**: 100 characters
- **Quotes**: Double quotes
- **Type annotations**: Required (mypy strict mode, `disallow_untyped_defs`)
- **Imports**: Sorted by isort (via ruff `I` rules)
- **Linter rules**: E, W, F, I, UP, B, C4, SIM, RUF (see `pyproject.toml [tool.ruff.lint]`)
- **Third-party type stubs**: `claude_agent_sdk` and `textual` have `ignore_missing_imports` overrides in mypy

## Testing

Tests use pytest with `asyncio_mode = "auto"`. Mock backends (`MockAgentBackend`) for unit tests. Test markers: `unit`, `integration`, `docker`, `slow`.

```
tests/
├── unit/           # Fast, isolated, no external deps
├── integration/    # May use mocks, tests component interactions
├── docker/         # Requires Docker daemon (excluded by default)
```

## Docker Notes

- Non-root user: `pentester` with sudo
- Workdir: `/workspace` (mounted from `./workspace`)
- LLM config persisted in `claude-config` Docker volume
- Auth modes via `PENTESTGPT_AUTH_MODE`: `manual` (default OAuth), `anthropic` (API key), `openrouter` (proxy)
- Pre-installed: nmap, netcat, curl, wget, git, ripgrep, tmux

## Legacy Version

The previous multi-LLM version (v0.15) is archived in `legacy/` (OpenAI, Gemini, Deepseek, Ollama, GPT4All). Excluded from linting/formatting via ruff `extend-exclude`.

```bash
cd legacy && pip install -e .
```

## Benchmark System

Standalone runner at `benchmark/standalone-xbow-benchmark-runner/`. CLI entry point: `pentestgpt-benchmark`.

```bash
cd benchmark/standalone-xbow-benchmark-runner
python3 run_benchmarks.py --range 1-10 --pattern-flag   # Run benchmarks 1-10
python3 run_benchmarks.py --all --pattern-flag          # Run all 104 benchmarks
python3 run_benchmarks.py --retry-failed                # Retry failed
```

## Modification Requirements

When modifying code, ensure:
- Adherence to existing architecture and patterns
- Comprehensive tests for new features
- Run tests after changes and ensure all pass before committing
- Keep documentation up to date with architectural changes