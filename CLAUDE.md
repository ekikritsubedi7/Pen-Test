# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

PentestGPT now centers on `pentestgpt_agent`, a ledger-based autonomous security
assessment framework. It runs three cooperating roles:

- **Instructor** plans scoped work and decides when the assessment can complete.
- **Executor** performs bounded task cards in a workspace.
- **Judge** validates evidence and accepts or rejects proposed findings.

The old fixed-stage `pentestgpt/` package and `pentestgpt` CLI were retired from
the active codebase. Historical benchmark reports and JSONL files may still
mention the old `pipeline` variant; new benchmark runs use only `single` and
`framework`.

**Stack:** Python 3.12+, uv, Docker, Claude Code CLI, OpenAI Codex CLI.
`unified_agent/` remains the shared backend substrate that lets
`pentestgpt_agent/` drive Claude Code or Codex through one normalized interface.
Do not delete `unified_agent/` unless you first migrate those imports into
`pentestgpt_agent/`.

## Common Commands

```bash
# Setup
uv sync

# Local framework run
uv run pentestgpt-agent \
  --goal "Capture the CTF flag for this authorized target" \
  --target http://127.0.0.1:8000

# Testing
make test
uv run pytest tests/test_framework_loop.py tests/test_roles.py -q

# Code quality
make lint
make format
make typecheck
make check

# Docker
make docker-build
make docker-login
make docker-auth-status
make docker-run TARGET=http://host.docker.internal:8000 BACKEND=claude
make docker-bench-agent-quick
make docker-bench-bestof3
```

`make docker-run` invokes `pentestgpt-agent` inside the tool image. Override
`GOAL=...`, `BACKEND=claude|codex`, and `MODEL=...` as needed.

## Docker Auth

The Docker image contains the maintained framework, `unified_agent`, the legacy
CLI, pentest tools, Claude Code CLI, and Codex CLI. The benchmark harness stays
outside the image and drives one fresh tool container per benchmark cell.

Auth persists in named volumes:

- `pentestgpt-claude` mounted at `/home/pentester/.claude`
- `pentestgpt-codex` mounted at `/home/pentester/.codex`

Claude and Codex auth are intentionally different. Claude can share a persisted
token across concurrent cells. Codex ChatGPT OAuth refresh tokens can race when
shared, so benchmark Codex concurrency defaults to `--max-codex 1` unless the
auth mode is explicitly safe for concurrent refresh.

## Architecture

### `pentestgpt_agent/`

- `contracts.py` — frozen dataclasses and strict schemas for `TaskCard`,
  `EvidenceBundle`, `FindingProposal`, `JudgeVerdict`, and `NodeStatus`.
- `scope.py` — derives advisory scope from the target and gates task cards and
  findings before they are accepted.
- `ledger.py` — single-writer durable run state under `runs/<run_id>/`:
  `scope.json`, `ledger.json`, `events.jsonl`, artifacts, and `report.md`.
- `framework_loop.py` — bounded orchestration loop. It plans when no work is
  open, dispatches ready leaves concurrently, folds evidence sequentially, and
  requires judge acceptance for findings and completion.
- `roles.py` — real role factories and `run_framework()`.
- `report.py` — renders reports from judge-accepted findings only.
- `__main__.py` — CLI entry point. Use `python -m pentestgpt_agent` or the
  `pentestgpt-agent` console script.
- `loop.py` — older minimal round-based loop kept for compatibility tests.

### `unified_agent/`

Shared backend substrate used by `pentestgpt_agent`:

- `agent.py` — `UnifiedAgent` / `SuperAgent` wrapper.
- `backends/claude_code.py` and `backends/codex.py` — backend adapters.
- `events.py`, `task.py`, `types.py` — normalized task/result/event types.
- `tools.py`, `tool_server.py`, `skills.py` — MCP-style tool and skill helpers.

This package is active, not dead code.

### `pentestgpt_legacy/`

The classic USENIX-2024 human-in-the-loop PentestGPT implementation, modernized
with a native multi-provider LLM layer. CLI scripts:

- `pentestgpt-legacy`
- `pentestgpt-legacy-connection`

Keep this separate from `pentestgpt_agent`; it is retained for historical and
interactive workflows.

## Testing

Suite layout:

- `tests/test_*.py` — framework and `unified_agent` unit tests.
- `tests/legacy/` — legacy package tests.
- `tests/docker/` — Docker build/container checks.
- `tests/smoke/` — live E2E tests, skipped unless explicitly enabled.

Useful focused checks:

```bash
uv run pytest tests/test_framework_loop.py tests/test_roles.py tests/test_report.py -q
uv run pytest tests/test_docker_bench_framework_score.py tests/test_best_of_report.py -q
uv run ruff check pentestgpt_agent/ unified_agent/ pentestgpt_legacy/ tests/
uv run mypy pentestgpt_agent/
```

Live smoke:

```bash
PENTESTGPT_LIVE_SMOKE=1 uv run pytest tests/smoke/test_live_framework_loop.py -v
```

## Benchmarking

The active XBOW Docker-network harness lives in `benchmark/pilot/`.

- `run_docker_bench.py --variant single` runs a naive single Claude/Codex agent
  against the target with a one-shot CTF prompt embedded in the benchmark runner.
- `run_docker_bench.py --variant framework` runs `python3 -m pentestgpt_agent`
  and scores stdout plus judge-accepted ledger/report findings.
- The retired `pipeline` variant is no longer generated by the active runner.
  Historical `pipeline` rows remain parseable by report tools for old result
  comparisons.

Parallel policy:

- Use default Compose project names for distinct benchmarks.
- Do not require `--unique-compose-project` for normal parallel runs.
- The runner uses `docker compose up --no-build` to avoid unintended rebuilds.
- Combos stay serial inside a benchmark; `--concurrency N` parallelizes across
  distinct benchmarks.
- Start real sweeps at `--concurrency 2`; move to `4` only after a small matrix
  is clean.

Default local verification after editing `pentestgpt_agent/`:

```bash
make docker-bench-agent-quick
```

Default best-of-three comparison after the old pipeline retirement:

```bash
make docker-bench-bestof3
```

This runs canaries, then `single` and `framework` sweeps over the configured
targets. Rerun with the same `BOF3_RUN_ID` to fill retryable infra/auth/provider
network rows.

## Repository Structure

```text
.
├── pentestgpt_agent/     # Maintained ledger-centered framework
├── unified_agent/        # Active backend-agnostic substrate for Claude/Codex
├── pentestgpt_legacy/    # Modernized classic interactive PentestGPT
├── benchmark/pilot/      # XBOW Docker-network benchmark harness and reports
├── tests/                # Framework, substrate, legacy, Docker, and smoke tests
├── Dockerfile            # Tool image for local runs and benchmarks
└── Makefile              # Development, Docker, and benchmark commands
```

## Modification Requirements

- Keep the maintained path (`pentestgpt_agent` + `unified_agent`) green.
- Preserve existing user changes in the worktree.
- Do not revive imports from the retired `pentestgpt/` package.
- Add focused tests for benchmark harness behavior before long live sweeps.
- Score framework benchmark results through judge-accepted findings/reports, not
  raw executor tool output.
