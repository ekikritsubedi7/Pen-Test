# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PentestGPT is an AI-powered autonomous penetration testing agent. It solves CTF challenges, Hack The Box machines, and authorized security assessments by driving a Claude Code agent through a multi-stage pipeline. Output is raw streaming to stdout.

**Published at USENIX Security 2024**: [Paper](https://www.usenix.org/conference/usenixsecurity24/presentation/deng)

**Stack:** Python 3.12+, uv, Claude Code CLI (the default agent backend spawns `claude -p` as a subprocess). The CTF pipeline is backend-pluggable: `--backend codex` instead drives OpenAI Codex (via the `unified_agent` Codex backend), so the same pipeline can run on Claude (`opus`/`sonnet`) or Codex (`gpt-5.5`/`gpt-5.4-mini`).

## Common Commands

```bash
# Setup
uv sync                                   # Install dependencies
uv run pentestgpt --target X              # Run locally

# Testing
make test                                 # Run all tests
make test-cov                             # Run tests with coverage
uv run pytest tests/integration/test_controller.py -v   # Run a single test file

# Code Quality
make lint                                 # Run ruff linter
make format                               # Format code with ruff
make typecheck                            # Run mypy (scoped to pentestgpt/)
make check                                # lint + typecheck

# Docker (the tool, with persistent Claude + Codex login)
make docker-build                         # Build the tool image (tool only; NO benchmark)
make docker-login                         # ONE-TIME: persist Claude + Codex logins into named volumes
make docker-run TARGET=… BACKEND=… MODEL=… MODE=…   # Run the pipeline against a target
```

Docker design notes: the image bundles the CTF pipeline + both CLIs (`claude`, `codex`) + `openai_codex`.
Logins persist in named volumes `pentestgpt-claude` / `pentestgpt-codex`. The two CLIs need **different**
auth handling because their token models differ:
- **Claude** — `claude setup-token` yields a long-lived token; `make docker-login` stores it at
  `~/.claude/oauth_token` in the volume and the entrypoint exports it as `CLAUDE_CODE_OAUTH_TOKEN`
  (`setup-token` does not write `.credentials.json`; macOS host creds are in the Keychain, not copyable).
- **Codex** — the container does its **own** `codex login` (NOT seeding/copying — ChatGPT refresh tokens
  are single-use, so a shared login 401s on first refresh). The `127.0.0.1:1455` OAuth callback is
  forwarded in via a `socat` hop (`-p 1455:8455` → `TCP:127.0.0.1:1455`).

`scripts/docker-login.sh` is **idempotent** (checks logins live, logs in only the missing one[s]);
`scripts/docker-auth-status.sh` + the entrypoint preflight report status. The benchmark is deliberately
NOT in the image. Full plan: `docs/docker-dev-plan.md`.

## Architecture

### Entry Point
- `pentestgpt/interface/main.py` — CLI entry, argument parsing, raw streaming output, telemetry setup.
- Command: `pentestgpt --target <IP/URL> [--mode ctf|pentest] [--backend claude|codex] [--model M] [--instruction "hint"] [--list-sessions] [--debug] [--no-telemetry]`
  - `--backend` (default `claude`) selects the runtime. With `codex`, `--model` takes a Codex id (`gpt-5.5`, `gpt-5.4-mini`; default `gpt-5.5`); reasoning effort is set via `PENTESTGPT_CODEX_EFFORT` (default `medium`). With `PENTESTGPT_BENCH=1`, the Codex backend prints a greppable `[CODEX_USAGE]` token line per turn (benchmark observability).

### Core Layer (`pentestgpt/core/`)
- **pipeline.py** — `PipelineOrchestrator`: runs a fixed sequence of stages, each with a fresh backend + controller. Data classes: `PipelineMode` (CTF/PENTEST), `StageDefinition` (name, display_name, `get_system_prompt`, `get_task_prompt`), `StageResult`, `PipelineResult` (`success`, `all_flags`, `total_cost`, `combined_output`). Each stage's output + flags are injected into the next stage's task prompt. `run()` executes **every** stage in order — it only breaks early on an explicit user `stop()`, and on a stage error it logs a warning and continues so later stages still get partial context. Flag capture does **not** short-circuit the pipeline.
- **pipelines.py** — Factory that assembles the stage lists. `CTF_STAGES` = recon → exploit (DFS) → walkthrough; `PENTEST_STAGES` = asset_identification → vulnerability_identification (BFS) → report. `get_stages(mode)` returns the list for a `PipelineMode`.
- **backend.py** — `AgentBackend` interface + two implementations. `ClaudeCodeBackend` spawns `claude -p` and parses streaming JSON into `AgentMessage`s (`MessageType`: TEXT, TOOL_START, TOOL_RESULT, RESULT, ERROR); supports session resume. `CodexBackend` wraps `unified_agent.backends.codex` (FULL_ACCESS sandbox, native shell) and translates its normalized `AgentEvent`s into the same `AgentMessage`s, so the pipeline is runtime-agnostic. `pipeline.py` picks the class from `config.backend`. Only assistant TEXT is flag-scanned (parity across backends); Codex `cost_usd` is 0 (ChatGPT-subscription billed) so it reports tokens instead.
- **controller.py** — `AgentController`: 5-state lifecycle (IDLE→RUNNING→PAUSED→COMPLETED→ERROR), pause/resume/stop/inject at message boundaries. Detects flags via `FLAG_PATTERNS`. Used per-stage by the orchestrator.
- **events.py** — `EventBus`: singleton pub/sub decoupling the agent from output consumers. `EventType`: STATE_CHANGED, MESSAGE, TOOL, FLAG_FOUND (agent → consumers); USER_COMMAND, USER_INPUT (control → agent).
- **session.py** — `SessionStore`: file-based JSON persistence in `~/.pentestgpt/sessions/` (`SessionInfo` / `SessionStatus`). A new session is created per stage. `--list-sessions` reads these. Note: `--resume` / `--session-id` are parsed in `main.py` but **not currently wired into the pipeline** — the orchestrator never calls `controller.run(resume_session_id=...)` — so they are no-ops today, even though the controller and `ClaudeCodeBackend` do support resume.
- **config.py** — `PentestGPTConfig` (pydantic-settings, `.env` support). Key fields: `llm_model` (default `claude-sonnet-4-5-20250929`), `backend` (`claude`/`codex`, default `claude`), `mode` (`ctf`/`pentest`), `working_directory` (default `./workspace`; overridable via the `WORKING_DIRECTORY` env var for isolated runs), `permission_mode` (default `bypassPermissions`), `target`, `custom_instruction`. (`max_iterations` exists with default 300 but is currently unused.) `load_config()` / `from_env()`.
- **langfuse.py** — Optional Langfuse telemetry. Subscribes to the `EventBus` and reports anonymized spans. `init_langfuse()` / `shutdown_langfuse()`; persistent user id in `~/.pentestgpt/user_id`. Disable with `--no-telemetry` or `LANGFUSE_ENABLED=false`.

### Stage Prompts (`pentestgpt/prompts/`)
- **stages.py** — Per-stage system/task prompt builders: `ctf_stage{1,2,3}_system_prompt` / `_task_prompt` and `pentest_stage{1,2,3}_system_prompt` / `_task_prompt`. Shared fragments: `_IDENTITY`, `_TOOLS`, `_FLAG_PATTERNS`, `_PERSISTENCE`, `_CTF_CATEGORIES`, `_FALLBACK_STRATEGIES`. Helper `_build_prior_context_block()` formats prior-stage results for the next stage.

### Next-Gen Agent Framework (`unified_agent/` + `pentestgpt_agent/`)

A newer architecture that supersedes the fixed-stage `pentestgpt/` pipeline with a dynamic,
ledger-centered loop. Runs three cooperating agents — **Instructor** (lead tester, owns the
workflow status), **Executor** (scoped task runner with a shell), **Judge** (independent,
evidence-grounded validator) — on a backend-agnostic substrate.

- **`unified_agent/`** — one `UnifiedAgent` drives Claude Code *or* Codex identically: same MCP
  stdio tools, Agent Skills, structured-output schemas, `SandboxPolicy`, resume, normalized
  events folded into `UnifiedResult`. The framework only constructs the Claude backend (it
  validates structured output natively; Codex silently drops malformed JSON).
- **`pentestgpt_agent/contracts.py`** — frozen dataclasses (`TaskCard`, `EvidenceBundle`,
  `CandidateFinding`, `FindingProposal`, `JudgeVerdict`, `NodeStatus`), three Codex-strict JSON
  schemas, and defensive `parse_instructor`/`parse_evidence`/`parse_verdict` that turn a backend's
  silent `structured_output=None` into a typed `ContractError`.
- **`pentestgpt_agent/scope.py`** — structured `Scope` enforced *before* dispatch (`check_card`)
  and on every finding (`check_finding`); `scope_from_target()` derives scope from a target URL.
  NOTE: advisory only — a `WORKSPACE_WRITE` executor has a real shell; true egress enforcement
  (proxy/container) is a documented TODO.
- **`pentestgpt_agent/ledger.py`** — the single-writer durable ledger. Run dir
  `runs/<run_id>/` with `scope.json`, `ledger.json` (snapshot, source of truth on reload),
  append-only `events.jsonl` (audit trail, never replayed), `artifacts/`, `report.md`. Typed
  mutators + DAG readiness (`recompute_ready`, `unsatisfiable_blocked`).
- **`pentestgpt_agent/framework_loop.py`** — `FrameworkLoop`: one ledger-owning coroutine.
  Plans only when no work is open → scope-gates + cycle-breaks cards → dispatches independent
  READY leaves concurrently (`asyncio.gather` wave) → folds evidence sequentially (single writer)
  → **mandatory judge gate** per finding and on completion (the instructor can only *propose*
  completion). `needs_more` spawns a **bounded** verifier task. All termination conditions are
  bounded (`max_rounds`, `max_total_dispatches`, `max_finding_verifications`).
- **`pentestgpt_agent/report.py`** — renders `report.md` from **judge-accepted findings only**;
  rejected proposals appear as false-positive notes.
- **`pentestgpt_agent/roles.py`** + **`__main__.py`** — real agent factories (instructor/judge
  `READ_ONLY`, executor `WORKSPACE_WRITE`), `run_framework()`, and the CLI:
  `uv run python -m pentestgpt_agent --goal "..." --target http://127.0.0.1:8000`.
- **`pentestgpt_agent/loop.py`** — the original minimal round-based `AgentLoop` (kept intact;
  shares the `LoopAgent` protocol with the framework).

Deferred to documented perf TODOs: intra-DAG concurrency via a ready-set pump (the one real seam),
a worker/queue actor mesh, event-sourced replay, model routing, token compression, cost budgeting.

## Key Patterns

- **Multi-Stage Pipeline**: `PipelineOrchestrator` runs stages sequentially. Each stage gets a fresh `ClaudeCodeBackend` + `AgentController` (the system prompt is fixed at backend construction, so a new backend is needed per stage). The output and flags of each stage are passed into the next stage's task prompt via `StageDefinition.get_task_prompt(config, prior_results)`.
- **Event-Driven**: Raw streaming mode subscribes to the `EventBus`; the agent emits events for state changes, messages, tools, and flags.
- **Singletons**: `EventBus.get()` for global access.
- **Abstract Backend**: The `AgentBackend` interface allows swapping the underlying agent runtime.
- **Flag Detection**: Regex patterns in `controller.py` (`FLAG_PATTERNS`) match `flag{}`, `FLAG{}`, `HTB{}`, `CTF{}`, generic `NAME{...}`, and 32-char hex.

## Testing

Tests use pytest with pytest-asyncio (mock backends for unit tests). Suite layout:
`tests/unit/` (fast, no externals), `tests/integration/` (controller, mocks), `tests/legacy/` (covers `pentestgpt_legacy`), `tests/docker/` (image/container, `-m docker`).

```bash
uv run pytest tests/ -v                                  # All tests
uv run pytest tests/integration/test_controller.py -v    # Single file
uv run pytest tests/unit/test_flag_detection.py::test_name  # Single test
```

The next-gen framework has fast fake-agent unit tests (`tests/test_{contracts,scope,ledger,framework_loop,report,roles}.py`)
that run in `make test`, plus a **live** E2E acceptance gate that drives real Claude agents against
a local stdlib HTTP fixture (vulnerable / hardened / out-of-scope cases). The live gate is skipped
by default and opt-in:

```bash
PENTESTGPT_LIVE_SMOKE=1 uv run pytest tests/smoke/test_live_framework_loop.py -v
```

Note: `make lint` / `make typecheck` cover `pentestgpt/` (+ legacy via lint); for the new package run
`uv run ruff check pentestgpt_agent/ unified_agent/` and `uv run mypy pentestgpt_agent/` explicitly.

## Benchmarking (xbow validation-benchmarks)

A host-based multi-model benchmark harness lives in **`benchmark/pilot/`** (see its `README.md` for
full docs + current status and `REPORT.md` for the latest results). It drives the CTF pipeline across
four model/runtime combos — Claude `opus`/`sonnet` and Codex `gpt-5.5`/`gpt-5.4-mini` — over the
[xbow validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks).

- **`run_pilot.py`** — for each challenge: `make build` (bakes `FLAG{sha256(UPPERCASE-DIR)}`) → fresh
  `docker compose up` per run → discover the loopback-published port → run
  `pentestgpt --target http://127.0.0.1:<port> --backend … --model …` with a timeout → judge success
  by the ground-truth flag appearing in captured stdout → teardown. Resumable (`results.jsonl`).
- **`report.py`** — renders `REPORT.md`: per-challenge × per-model table + aggregates; excludes
  infrastructure failures (build/boot errors) from solve denominators.
- **Status**: a 13-challenge × 4-model *pilot* ran (not the full 59 medium/hard set). Remaining work —
  full sweep, **dockerized/isolated execution** (so scans don't hit host endpoint monitoring), arm64
  infra fixes (`mysql:5.7`, EOL-buster images), retries, cost accounting — is tracked in
  `benchmark/pilot/README.md` and `docs/redesign/pentestgpt-redesign-decisions.html` (Roadmap card).

> The benchmark fixtures are a **separate** checkout (an `xbow-validation-benchmarks` submodule, e.g.
> at a sibling path), not vendored into this repo. The agents run real offensive tooling (nmap,
> gobuster, exploit payloads) against loopback Docker targets — run them in an environment where that
> is authorized and won't trip local security monitoring.

## Repository Structure

```
.
├── pentestgpt/           # Autonomous agent (fixed-stage pipeline, Claude Code CLI backend)
│   ├── core/             # pipeline + pipelines factory, controller, backend, events, session, config, langfuse
│   ├── interface/        # CLI entry point (raw streaming)
│   └── prompts/          # Stage prompt builders (stages.py)
├── unified_agent/        # Backend-agnostic substrate: one agent over Claude Code or Codex
│   └── backends/         # claude_code, codex
├── pentestgpt_agent/     # Next-gen ledger-centered framework (instructor/executor/judge)
│                         #   contracts, scope, ledger, framework_loop, report, roles, __main__, loop
├── pentestgpt_legacy/    # Modernized legacy: interactive 3-session + PTT, multi-LLM
│   ├── llm/              # Native per-provider LLM layer (registry, factory, client, providers)
│   ├── utils/            # Orchestrator (pentest_gpt.py) + REPL helpers
│   └── prompts/          # Classic PTT/session prompts
├── benchmark/pilot/      # Multi-model xbow benchmark harness (run_pilot.py, report.py, REPORT.md)
├── tests/                # unit/ integration/ legacy/ docker/ smoke/ + flat test_*.py (substrate + framework)
└── Makefile              # Development commands
```

### Modernized Legacy (`pentestgpt_legacy/`)

The classic USENIX-2024 human-in-the-loop tool, rebuilt on a native multi-provider LLM
layer. CLI: `pentestgpt-legacy` (`--list-models`, `--smoke-test`, `--reasoning-model`,
`--parsing-model`, `--generation-model`, `--base-url`). It runs three cooperating LLM sessions
(reasoning / generation / parsing) that maintain a Pentesting Task Tree (PTT).

- **llm/registry.py** — single source of truth for supported models (`ModelSpec` / `PROVIDERS`,
  web-verified IDs). `--list-models` and the README table render from it.
- **llm/factory.py** — `get_client(model_name)` -> `LLMClient`; resolves provider, builds it.
- **llm/client.py** — `LLMClient` bridges async providers to the core's synchronous
  `send_new_message` / `send_message` (drop-in for the old `LLMAPI`); holds per-conversation history.
- **llm/providers/** — `OpenAICompatibleProvider` (OpenAI + DeepSeek/Ollama/xAI/Qwen/Moonshot via
  base_url; Responses-API fallback for `*-pro`/`*-codex`), `AnthropicProvider`, `GeminiProvider`.
- **llm/config.py** — pydantic-settings credentials (per-provider keys + base-url overrides).
- **smoke_test.py** — `--smoke-test` makes a real round-trip per configured model (acceptance gate).
  `test_connection.py` (script `pentestgpt-legacy-connection`) does a lighter per-provider check.

Note: `make typecheck` is scoped to `pentestgpt/`; the legacy package is covered by ruff
(`make lint`) and `tests/legacy/`. Run `uv run mypy pentestgpt_legacy/llm/` for its typed core.

## Modification Requirements

When modifying code, ensure:
- Adherence to existing architecture and patterns.
- Comprehensive tests for new features.
- Run the tests after changes and keep the documentation (this file and the README) in sync with any architectural changes. All tests must pass after modifications.
