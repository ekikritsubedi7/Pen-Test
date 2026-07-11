# AGENT.md

Codex-facing working notes for this repository. Keep this aligned with
`CLAUDE.md` when benchmark or agent architecture changes. Do not edit README
files unless the user explicitly asks.

## Project Map

- `pentestgpt_agent/` is the maintained ledger-centered framework:
  instructor, executor, judge, accepted findings, durable ledger, and generated
  report.
- `unified_agent/` is active shared infrastructure for Claude Code and Codex.
  `pentestgpt_agent` imports it directly; do not delete it without a deliberate
  migration.
- `pentestgpt_legacy/` is the modernized interactive legacy tool.
- `benchmark/pilot/` is the XBOW benchmark workspace and source of truth for
  Docker-network benchmark commands, JSONL outputs, and reports.
- The old fixed-stage `pentestgpt/` package and `pentestgpt` CLI have been
  retired from the active codebase. Historical JSONL/report files may still
  mention the old `pipeline` variant.

## Common Commands

```bash
uv sync
make lint
make typecheck
uv run pytest tests/test_framework_loop.py tests/test_roles.py -q
uv run pytest tests/test_docker_bench_framework_score.py tests/test_best_of_report.py -q
```

Docker image and auth setup:

```bash
make docker-build
make docker-login
make docker-auth-status
```

Run the maintained framework locally:

```bash
uv run pentestgpt-agent \
  --goal "Capture the CTF flag for this authorized target" \
  --target http://127.0.0.1:8000
```

Default local verification after editing `pentestgpt_agent/`:

```bash
make docker-bench-agent-quick
```

Default best-of-three comparison:

```bash
make docker-bench-bestof3
```

This now runs canaries plus `single` and `framework` sweeps. It no longer runs
the retired fixed-stage `pipeline` variant.

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

Maintained framework smoke:

```bash
make docker-bench-agent-quick
```

Best-of-three comparison:

```bash
make docker-bench-bestof3
```

## Safety

The benchmark agents run real offensive tooling against local Docker CTF
targets. Only run the benchmark where this is authorized and where endpoint
security monitoring will not interfere with measurements. The Docker-network
harness attacks internal container URLs, but model CLIs still need outbound
HTTPS to their providers.

## Editing Expectations

- Keep documentation and benchmark commands in sync when runner behavior changes.
- Preserve existing user changes in the worktree.
- Do not reintroduce imports from the retired `pentestgpt/` package.
- Add or update focused tests for benchmark runner behavior before long live
  sweeps.
- For `pentestgpt_agent`, score through judge-accepted reports/ledger findings,
  not raw executor tool output.
