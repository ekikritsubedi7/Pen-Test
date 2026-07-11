# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

PentestGPT now centers on **`pentestgpt_agent/`**, a durable, memory-backed
penetration-testing loop. It is a self-contained nested uv project (its own
`pyproject.toml`, `uv.lock`, and `.venv`) and is the single maintained framework.

It runs two cooperating LLM roles over a deterministic core:

- **Supervisor** — read-only; proposes at most one new task and leases at most
  one ready task per decision. It never executes tools.
- **Executor** — performs only the one leased task, bounded by an explicit task
  kind and per-kind turn budget.

Deterministic code (not the model) owns scope, task/dependency rules, leases,
returned-trace identity, evidence provenance, retry safety, and canonical state
transitions. Every episode is fresh; provider conversation history is not memory.

This loop **reclaimed the `pentestgpt_agent` name** from an earlier, unrelated
design: the previous framework at this path was a ledger-based
Instructor/Executor/Judge implementation, which was removed and replaced by the
code described here. The older fixed-stage `pentestgpt/` package was also removed.
Do not revive either design; historical benchmark reports may still mention the
retired `pipeline`/ledger `framework` variants.

**Stack:** Python 3.12+, uv, Docker, Claude Code CLI, OpenAI Codex CLI. The
framework drives Claude Code or Codex through the external **`unified-agent`**
package, consumed as a pinned **git dependency** from
`github.com/PentestGPT-Project/UnifedAgentWrapper` (the renamed former
`UnifiedAgentPoC`). A vendored `unified_agent/` copy still lives at the repo root
for `pentestgpt_legacy` and the parent build; the new framework does **not** use
it — `test_dependency.py` guards against the vendored copy shadowing the git one.

## Where to work

Almost all framework work happens **inside `pentestgpt_agent/`**. Run its uv
commands from that directory:

```bash
cd pentestgpt_agent
uv sync --extra claude          # or --extra codex / --extra all
uv run pentestgpt-agent --goal "Capture the CTF flag for this authorized target" \
  --target http://127.0.0.1:8000 --backend claude
uv run pentestgpt-agent-audit --help
uv run pytest -q
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src
```

See `pentestgpt_agent/README.md` and `pentestgpt_agent/CONTEXT.md` for
the domain language, invariants, and CLI/audit usage.

## Common Commands (from the repo root)

The top-level Makefile is the umbrella dev interface. Quality/test targets now
run the nested framework's own gate so it is actually covered:

```bash
# Run the framework against an authorized target (delegates to the nested CLI)
make run TARGET=http://127.0.0.1:8000 BACKEND=claude

# Tests / quality
make test              # parent substrate + benchmark-harness tests
make test-agent-new    # the nested framework suite
make check             # parent lint + the full nested gate (ruff, format, mypy, pytest)
make check-agent-new   # just the nested gate
make ci                # full CI simulation across both
```

## Docker Auth

The Docker image contains the substrate, the legacy CLI, pentest tools, Claude
Code CLI, and Codex CLI. **The maintained framework is not baked into the image
yet** — running `pentestgpt_agent` in-container is a pending rewire (see the
Benchmarking note). The benchmark harness stays outside the image and drives one
fresh tool container per benchmark cell.

Auth persists in named volumes:

- `pentestgpt-claude` mounted at `/home/pentester/.claude`
- `pentestgpt-codex` mounted at `/home/pentester/.codex`

Claude and Codex auth are intentionally different. Claude can share a persisted
token across concurrent cells. Codex ChatGPT OAuth refresh tokens can race when
shared, so benchmark Codex concurrency defaults to `--max-codex 1` unless the
auth mode is explicitly safe for concurrent refresh.

## Architecture

### `pentestgpt_agent/src/pentestgpt_agent/`

- `agents.py` — Supervisor/Executor roles, prompts, schemas, and output parsing.
- `plan.py` — typed task language and the deterministic plan compiler (scope,
  single-new-task, and dependency rules).
- `execution.py` — Executor delta validation and exact, receipt-grounded
  trace-evidence resolution (a completed task must cite captured evidence).
- `memory.py` — single-writer SQLite kernel: schema, snapshots, leases, and
  atomic commits with optimistic revision checks.
- `trace.py` — durable append-only episode inputs/events/outputs, hashes,
  usage/cost, plus the `EpisodeRunner`.
- `loop.py` — crash-resumable one-task-at-a-time loop; recovers persisted traces
  before re-invoking the model and records deterministic failure transactions.
- `trial.py` — real-provider trial CLI (`pentestgpt-agent`).
- `audit.py` — deterministic state/trace/oracle audit CLI (`pentestgpt-agent-audit`).
- `scripts/run_xbow.py` — the framework's own XBOW Docker benchmark runner.

### `unified_agent/` (repo-root, vendored)

Backend substrate retained for `pentestgpt_legacy` and the parent build. The new
framework consumes the equivalent package from the git wrapper instead. Do not
delete this copy without first checking `pentestgpt_legacy` and the parent
`pyproject.toml` wheel packages.

### `pentestgpt_legacy/`

The classic USENIX-2024 human-in-the-loop PentestGPT, modernized with a native
multi-provider LLM layer. CLI scripts: `pentestgpt-legacy`,
`pentestgpt-legacy-connection`. Retained for historical and interactive workflows.

## Testing

- Nested framework: `cd pentestgpt_agent && uv run pytest -q` (its `tests/`
  cover the plan compiler, memory kernel, evidence, trace recovery, the loop,
  local benchmark, CLIs, and an opt-in live-provider test).
- Parent repo `tests/`: the vendored `unified_agent` substrate and the
  benchmark-harness tests. Note the vendored `test_claude_backend.py` /
  `test_codex_backend.py` can fail on backend-SDK drift independent of framework
  work; the git-sourced framework suite is the source of truth for the loop.

## Benchmarking

The XBOW Docker-network harness lives in `benchmark/pilot/`. **Benchmarks are
currently deprioritized.** The harness plus the Dockerfile still target the old
in-image framework, so the `--variant framework` path and the Docker-bench
Makefile targets need a rewire onto `pentestgpt_agent` (or its own
`scripts/run_xbow.py`) before they produce valid framework rows again. The
`--variant single` naive baseline is unaffected.

## Repository Structure

```text
.
├── pentestgpt_agent/  # Maintained framework (nested uv project)
├── unified_agent/         # Vendored substrate for legacy + parent build
├── pentestgpt_legacy/     # Modernized classic interactive PentestGPT
├── benchmark/pilot/       # XBOW Docker-network benchmark harness (framework path pending rewire)
├── tests/                 # Substrate, benchmark-harness, and Docker tests
├── Dockerfile             # Tool image (substrate + legacy; framework not baked in yet)
└── Makefile               # Dev/quality umbrella over the nested framework
```

## Modification Requirements

- Keep the maintained path (`pentestgpt_agent` + the git `unified-agent`) green:
  `make check` must pass.
- Preserve existing user changes in the worktree.
- Do not revive the retired ledger-based Instructor/Executor/Judge design (the
  prior occupant of this name) or the old fixed-stage `pentestgpt/` package.
- When bumping the `unified-agent` pin, update `[tool.uv.sources]` in
  `pentestgpt_agent/pyproject.toml`, run `uv lock`, and re-run the suite.
- Add focused tests for benchmark harness behavior before long live sweeps.
