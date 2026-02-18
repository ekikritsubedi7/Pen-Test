# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PentestGPT is an AI-powered autonomous penetration testing agent with a terminal user interface (TUI). It uses an agentic pipeline to solve CTF challenges, Hack The Box machines, and authorized security assessments.

**Published at USENIX Security 2024**: [Paper](https://www.usenix.org/conference/usenixsecurity24/presentation/deng)

**Stack:** Python 3.12+, uv, Docker (Ubuntu 24.04), Textual (TUI), Rich (CLI), Agent SDK

## Common Commands

```bash
# Development
uv sync                           # Install dependencies
uv run pentestgpt --target X      # Run locally

# Testing
make test                         # Run all tests
make test-cov                     # Run tests with coverage
uv run pytest tests/test_controller.py -v  # Run single test file

# Code Quality
make lint                         # Run ruff linter
make format                       # Format code with ruff
make typecheck                    # Run mypy type checking
make check                        # All checks (lint + typecheck)

# Docker Workflow
make install                      # Build Docker image
make connect                      # Connect to container (main usage)
make stop                         # Stop container
make clean-docker                 # Remove everything including config
```

## Architecture

### Entry Point
- `pentestgpt/interface/main.py` - CLI entry, argument parsing, mode selection
- Command: `pentestgpt --target <IP/URL> [--mode ctf|pentest] [--instruction "hint"] [--non-interactive] [--raw] [--debug]`

### Core Layer (`pentestgpt/core/`)
- **pipeline.py** - `PipelineOrchestrator`: Runs 3 stages sequentially, each with a fresh backend + controller. Data classes: `PipelineMode`, `StageDefinition`, `StageResult`, `PipelineResult`
- **pipelines.py** - Factory: `CTF_STAGES`, `PENTEST_STAGES`, `get_stages(mode)` — wires stage definitions to prompt builders
- **agent.py** - `PentestAgent`: Wraps the LLM agent, handles flag detection; `run_pentest()` convenience function uses `PipelineOrchestrator`
- **backend.py** - `AgentBackend` interface + `ClaudeCodeBackend` implementation (framework-agnostic design)
- **controller.py** - `AgentController`: 5-state lifecycle (IDLE->RUNNING->PAUSED->COMPLETED->ERROR), pause/resume at message boundaries. Used per-stage by the pipeline orchestrator
- **events.py** - `EventBus`: Singleton pub/sub for TUI-agent decoupling (STATE_CHANGED, MESSAGE, TOOL, FLAG_FOUND events)
- **session.py** - `SessionStore`: File-based persistence in `~/.pentestgpt/sessions/`, supports session resumption
- **config.py** - Pydantic settings with `.env` file support; includes `mode: Literal["ctf", "pentest"]`

### Interface Layer (`pentestgpt/interface/`)
- **tui.py** - Textual TUI app with real-time activity feed, F1 help, Ctrl+P pause, Ctrl+Q quit
- **components/** - ActivityFeed, SplashScreen, tool-specific Renderers

### System Prompts (`pentestgpt/prompts/`)
- **pentesting.py** - `CTF_SYSTEM_PROMPT`: Original monolithic prompt (retained for backward compat)
- **stages.py** - Stage-specific prompt builders for both pipelines. Shared fragments (`_IDENTITY`, `_TOOLS`, `_FLAG_PATTERNS`, `_PERSISTENCE`, `_FALLBACK_STRATEGIES`) extracted from the original prompt. 6 CTF + 6 Pentest builder functions

## Key Patterns

- **Multi-Stage Pipeline**: `PipelineOrchestrator` runs 3 stages sequentially. Each stage gets a fresh `ClaudeCodeBackend` + `AgentController` (system prompt is set at connect time, so a new backend is needed per stage). Prior stage output is passed as context to the next stage's task prompt.
- **Two Modes**: CTF (Recon → DFS Exploit → Walkthrough) and Pentest (Asset ID → BFS Vuln ID → Report). Selected via `--mode ctf|pentest` or `config.mode`.
- **Event-Driven**: TUI subscribes to EventBus; agent emits events for state changes, messages, flags
- **Singletons**: `EventBus.get()`, `get_global_tracer()` for global access
- **Abstract Backend**: `AgentBackend` interface allows swapping LLM backends
- **Flag Detection**: Regex patterns in controller.py match `flag{}`, `HTB{}`, `CTF{}`, 32-char hex

## Testing

Tests use pytest with pytest-asyncio. Mock backends for unit tests.

```bash
uv run pytest tests/ -v                           # All tests
uv run pytest tests/test_controller.py -v         # Single file
uv run pytest tests/test_controller.py::test_name # Single test
```

## Docker Notes

- Non-root user: `pentester` with sudo
- Workdir: `/workspace` (mounted from `./workspace`)
- LLM config persisted in `claude-config` volume
- Pre-installed: nmap, netcat, curl, wget, git, ripgrep, tmux

## Legacy Version

The previous multi-LLM version (v0.15) is archived in `legacy/`. It supports:
- OpenAI (GPT-4o, o3, o4-mini)
- Google Gemini
- Deepseek
- Ollama (local LLMs)
- GPT4All

To develop on the legacy version:
```bash
cd legacy
pip install -e .
```

## Benchmark System

Use the standalone benchmark runner at `benchmark/standalone-xbow-benchmark-runner/`:

```bash
cd benchmark/standalone-xbow-benchmark-runner

python3 run_benchmarks.py --range 1-10 --pattern-flag   # Run benchmarks 1-10
python3 run_benchmarks.py --all --pattern-flag          # Run all 104 benchmarks
python3 run_benchmarks.py --retry-failed                # Retry failed benchmarks
python3 run_benchmarks.py --dry-run --range 1-5         # Preview without executing
```

See `benchmark/standalone-xbow-benchmark-runner/README.md` for full documentation.

## Repository Structure

```
.
├── pentestgpt/           # Main package (agentic version)
│   ├── core/             # Pipeline, agent, controller, events, session
│   ├── interface/        # TUI and CLI
│   ├── prompts/          # System prompts (pentesting.py, stages.py)
│   ├── benchmark/        # Benchmark runner module
│   └── tools/            # Tool framework
├── benchmark/            # Benchmark suites
│   ├── xbow-validation-benchmarks/  # 104 XBOW benchmarks
│   └── standalone-xbow-benchmark-runner/  # Benchmark runner
├── tests/                # Test suite
├── workspace/            # Runtime workspace (Docker mount)
├── legacy/               # Archived v0.15 (multi-LLM)
├── Dockerfile            # Ubuntu 24.04 container
├── docker-compose.yml    # Container orchestration
└── Makefile              # Development commands
```

## Modification Requirements

When modifying code, ensure:
- Adherence to existing architecture and patterns
- Comprehensive tests for new features
- Ensure to run tests after changes, and do further updates to ensure code quality. Always keep the documentation up to date with any architectural changes. Also ensure all tests pass after modifications.