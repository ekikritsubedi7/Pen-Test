# AGENT.md

Codex-facing working notes for this repository. Keep this aligned with
`CLAUDE.md` when benchmark or agent architecture changes. Do not edit README
files unless the user explicitly asks.

## Project Map

- `pentestgpt_agent_new/` is the maintained framework: a self-contained nested
  uv project running a Supervisor (read-only planner) and an Executor over a
  deterministic SQLite-backed, crash-resumable loop. Work inside it and run its
  uv commands from that directory. See its `README.md` / `CONTEXT.md`.
- `unified_agent/` (repo root) is a vendored substrate copy for `pentestgpt_legacy`
  and the parent build. The new framework instead consumes the equivalent
  `unified-agent` package as a pinned **git dependency** from
  `github.com/PentestGPT-Project/UnifedAgentWrapper` (renamed former
  `UnifiedAgentPoC`). Do not delete the vendored copy without a deliberate check.
- `pentestgpt_legacy/` is the modernized interactive legacy tool.
- `benchmark/pilot/` is the XBOW benchmark workspace for Docker-network commands,
  JSONL outputs, and reports.
- The prior ledger-centered `pentestgpt_agent/` (instructor/executor/judge) and
  the old fixed-stage `pentestgpt/` package have been **removed**. Historical
  JSONL/report files may still mention the retired `pipeline`/ledger variants.

## Common Commands

Framework work happens inside the nested project:

```bash
cd pentestgpt_agent_new
uv sync --extra claude
uv run pentestgpt-agent-new --goal "Capture the CTF flag for this authorized target" \
  --target http://127.0.0.1:8000 --backend claude
uv run pentestgpt-agent-audit --help
uv run pytest -q && uv run ruff check src tests && uv run mypy src
```

From the repo root, the umbrella Makefile covers the nested framework:

```bash
make run TARGET=http://127.0.0.1:8000 BACKEND=claude
make check           # parent lint + nested ruff/format/mypy/pytest
make test-agent-new  # nested suite only
```

Docker image and auth setup (note: the framework is not baked into the image yet):

```bash
make docker-build
make docker-login
make docker-auth-status
```

## Docker Benchmark Rules

Use `benchmark/pilot/run_docker_bench.py` for comparable benchmark results. It is
host-driven: the runner starts each XBOW target with Docker Compose, discovers
the target container's internal Docker-network URL, runs one fresh
`pentestgpt:latest` tool container on that network, appends one JSONL row, and
tears the target down.

Important rules:

- Keep the scheduler host-driven unless there is a concrete reason to move it.
  This avoids adding another Docker socket mount failure point.
- Do not require `--unique-compose-project` for normal parallel runs. XBOW
  images are pre-built under fixture default project names, and synthetic
  project names can make Compose look for missing image tags.
- Use `--concurrency N` to run distinct benchmarks in parallel. Combos stay
  serial inside one benchmark, so the same default Compose project is not
  attacked twice at once.
- Fixed host `ports:` are automatically serialized when they overlap. Dynamic
  ports such as `ports: [80]` can run in parallel.
- Codex benchmark cells default to `--max-codex 1` because shared ChatGPT OAuth
  refresh tokens can race. Only pass `--max-codex 0` when the Codex auth mode is
  safe under concurrent refresh.
- Infra/auth/liveness/Docker-run/provider-network/interrupted rows are
  diagnostic and retryable. They stay in JSONL logs but do not count as completed
  valid attempts.

## Benchmark Smokes

Naive single-agent smoke:

```bash
cd benchmark/pilot
PILOT_COMBOS="claude-sonnet" uv run python run_docker_bench.py \
  --variant single \
  --benchmarks XBEN-001-24,XBEN-068-24 \
  --timeout 900 \
  --concurrency 2 \
  --out docker_single_smoke.jsonl
```

Framework smoke and best-of-three (`make docker-bench-agent-quick` /
`make docker-bench-bestof3`) currently target the removed in-image framework and
are **pending a rewire** onto `pentestgpt_agent_new` (benchmarks deprioritized).
The naive `--variant single` path above is unaffected.

## Safety

The benchmark agents run real offensive tooling against local Docker CTF
targets. Only run the benchmark where this is authorized and where endpoint
security monitoring will not interfere with measurements. The Docker-network
harness attacks internal container URLs, but model CLIs still need outbound
HTTPS to their providers.

## Editing Expectations

- Keep documentation and benchmark commands in sync when runner behavior changes.
- Preserve existing user changes in the worktree.
- Do not reintroduce imports from the removed `pentestgpt_agent/` or `pentestgpt/`.
- Add or update focused tests for benchmark runner behavior before long live
  sweeps.
- For the framework, evidence is validated against the durable episode trace
  (exact, receipt-grounded), not raw executor stdout.
