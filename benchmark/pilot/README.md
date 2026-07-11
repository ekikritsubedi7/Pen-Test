# PentestGPT multi-model benchmark results

This directory tracks the **autonomous PentestGPT CTF pipeline** against the
[xbow-engineering/validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks).
It contains the original host-loopback harness plus the current Docker-network baseline, comparing
four model/runtime combinations across the staged pipeline, a pure single-agent baseline, and the
next-gen `pentestgpt_agent` framework smoke result:

| Combo | Runtime | Model id | Billing |
|---|---|---|---|
| Claude Opus | Claude Code CLI (`claude -p`) | `opus` | API $ |
| Claude Sonnet | Claude Code CLI (`claude -p`) | `sonnet` | API $ |
| Codex gpt-5.5 | OpenAI Codex (`app-server` SDK) | `gpt-5.5` | ChatGPT sub (tokens) |
| Codex gpt-5.4-mini | OpenAI Codex (`app-server` SDK) | `gpt-5.4-mini` | ChatGPT sub (tokens) |

This was enabled by making the pipeline backend-pluggable: `pentestgpt --backend {claude,codex}`
(`CodexBackend` in `pentestgpt/core/backend.py`).

> **Safety / authorization.** The agents run *real* offensive tooling (nmap, gobuster, nikto,
> sqlmap, command-injection / deserialization RCE payloads) against the benchmark targets. Run this
> **only** where that is authorized and where it will not trip local endpoint-security monitoring.
> The older host-loopback pilot was halted mid-sweep for exactly this reason. The current Docker
> baseline avoids host-loopback target URLs by running the tool container on the target Docker network.

---

## Files

| File | Purpose |
|---|---|
| `run_pilot.py` | Orchestrator: build → up → port-discover → run agent(s) → flag-check → teardown. Resumable. |
| `report.py` | Renders `REPORT.md` (per-challenge × per-model table + aggregates) from `results.jsonl`. |
| `results.jsonl` | One JSON record per `(challenge, model)` run. Source of truth; re-run skips completed pairs. |
| `logs/<challenge>__<combo>.log` | Full captured stdout per run. |
| `REPORT.md` | Generated report for the older host-loopback pilot. |
| `docker_results.jsonl` | Source-of-truth records for the completed Docker-network **pipeline** baseline. |
| `DOCKER_REPORT.md` | Current comparable Docker-network baseline report. |
| `docker_logs/<challenge>__<combo>.log` | Full captured stdout per Docker-network run. |
| `docker_repeats.jsonl` | Repeat/supplemental Docker-network records. Legacy rows without `variant` are old pipeline repeats; new `pentestgpt_agent` framework rows are explicitly marked `variant=framework`; multiple `attempt` values may coexist. |
| `run_docker_bench.py` | Docker-network runner: build → up → discover container IP/net → `docker run` the tool image on that net → flag-check → teardown. `--variant {single,pipeline,framework}`. Resumable by `(challenge, combo, variant, attempt)`. |
| `docker_single_results.jsonl` | Records for the **pure single-agent** baseline (one bare `claude -p` / `codex exec` per target). |
| `docker_framework_results.jsonl` | Records for the next-gen **framework** variant (`python3 -m pentestgpt_agent` instructor/executor/judge). |
| `report_comparison.py` | Renders `DOCKER_COMPARISON.md` — pipeline vs. single-agent vs. framework, joined per (challenge, model). |
| `DOCKER_COMPARISON.md` | Generated pipeline/single/framework comparison report. |
| `docker_bestof3_*.jsonl` | Robust rerun files for first-three-valid-attempt best-of-k comparisons. |
| `report_best_of.py` | Renders `DOCKER_BEST_OF_3.md`, excluding infra/auth/liveness/Docker-run/interrupted rows from valid-attempt counts. |
| `run_bestof3_suite.py` | Runs the final best-of-three suite: canary, `single`, `pipeline`, `framework`, then report generation and completion validation. |
| `benchmark_sets.json` | Version-controlled registry of **named, toggleable** challenge sets. Each challenge carries an `enabled` flag plus `level`/`tags`/`solved_by_framework`/`note` metadata. Seeded with `hard-open`. |
| `bench_set.py` | Agent-friendly CLI over `run_docker_bench.py`: `list` / `ids` / `enable` / `disable` / `run` for a named set. Resolves `XBEN_ROOT`, auto-suggests parallelism, and drives Docker. |
| `selected.json` | The challenge set used for the last `run_pilot.py` run (gitignored write-only artifact; superseded by `benchmark_sets.json` for the Docker path). |

## Prerequisites

- Docker (running), `make`, `openssl`, `curl`.
- The xbow fixtures checked out locally (a separate `xbow-validation-benchmarks` checkout). Set the
  path with `XBEN_ROOT` for `run_docker_bench.py` or at the top of `run_pilot.py` (`BENCH_ROOT`) for
  the older host-loopback runner.
- For Docker-network runs: build the tool image and persist CLI auth first:
  `make docker-build`, `make docker-login`, then verify with `make docker-auth-status`.
- For host-loopback runs only: authenticated `claude` CLI and `codex` CLI on the host `PATH`.
- `uv sync` in the repo root.

## Usage: host-loopback harness

```bash
cd benchmark/pilot

# Full candidate-pool auto-selection (builds candidates, keeps the first PILOT_SIZE that serve):
uv run python run_pilot.py --timeout 540 --concurrency 3

# Explicit challenge list (skips auto-selection):
uv run python run_pilot.py --benchmarks XBEN-001-24,XBEN-080-24 --timeout 540 --concurrency 3

# Smoke a single combo (env filter):
PILOT_COMBOS="claude-sonnet" uv run python run_pilot.py --benchmarks XBEN-079-24

# (Re)render the report from collected results — pure aggregation, runs nothing:
uv run python report.py
```

Useful env vars: `PILOT_CODEX_EFFORT` (default `medium`), `PILOT_COMBOS` (subset of combo keys),
`DOCKER_DEFAULT_PLATFORM=linux/amd64` (force amd64 emulation for arm64-incompatible images).

These commands reproduce/update the historical `REPORT.md` host-loopback report. `DOCKER_REPORT.md`
is the committed Docker-network baseline.

## Usage: Docker-network harness + comparison variants

`run_docker_bench.py` runs container-to-container (no host-loopback target URL): it brings the target
up with Compose, discovers the target container's internal `172.x` IP + Docker network, and `docker
run`s the tool image on that same network. It builds the image-side auth from the persisted volumes
(`pentestgpt-claude` / `pentestgpt-codex`), so run `make docker-build` + `make docker-login` first.

```bash
cd benchmark/pilot

# "Pure single agent" baseline — ONE bare `claude -p` / `codex exec` per target, fed a one-shot
# prompt built from PentestGPT's own fragments (pentestgpt/prompts/stages.ctf_single_agent_*).
uv run python run_docker_bench.py --variant single            # default: the 10 baseline targets
uv run python run_docker_bench.py --variant single --benchmarks XBEN-068-24,XBEN-079-24

# Inspect the exact docker command + assembled prompt without running anything:
uv run python run_docker_bench.py --variant single --benchmarks XBEN-068-24 --dry-run

# Smoke one combo:
PILOT_COMBOS="claude-sonnet" uv run python run_docker_bench.py --benchmarks XBEN-068-24

# Optional: refresh the *pipeline* baseline under the identical harness/image (-> docker_pipeline_results.jsonl):
uv run python run_docker_bench.py --variant pipeline

# Parallel smoke: two different benchmark Compose projects run at once; combos remain serial
# inside each benchmark, so the same target stack is never attacked by two agents at once.
PILOT_COMBOS="claude-sonnet" uv run python run_docker_bench.py \
  --variant pipeline \
  --benchmarks XBEN-001-24,XBEN-068-24 \
  --timeout 900 \
  --concurrency 2 \
  --out docker_parallel_smoke.jsonl

# Final best-of-3 comparison: native single agent vs pentestgpt pipeline vs pentestgpt_agent.
cd ../..
make docker-bench-bestof3
cd benchmark/pilot

# Next-gen framework smoke/benchmark. --source-root mounts the current checkout at /app so the
# container can use local Python changes without rebuilding the tool image.
cd ../..
make docker-bench-agent-quick
cd benchmark/pilot

# Equivalent raw runner form for custom sweeps:
PILOT_COMBOS="claude-sonnet" uv run python run_docker_bench.py \
  --variant framework \
  --image pentestgpt:latest \
  --source-root ../.. \
  --benchmarks XBEN-080-24 \
  --timeout 1200

# Render the pipeline/single/framework comparison (pure aggregation, runs nothing):
uv run python run_docker_bench.py --report     # or: uv run python report_comparison.py
```

The single variant writes `docker_single_results.jsonl`; the comparison joins it against the
canonical `docker_results.jsonl` pipeline baseline. The framework variant writes
`docker_framework_results.jsonl` by default and can also append to `docker_repeats.jsonl` via
`--out docker_repeats.jsonl`; its score comes from stdout plus generated
`report.md` and judge-accepted `ledger.json` findings, not raw executor logs. Re-run a benchmark
pass with a new `--attempt N`; repeat rows are appended, and `DOCKER_COMPARISON.md` uses the
latest row for each challenge/model/variant.
For robust final results, use `make docker-bench-bestof3`. It runs a framework canary, then
timestamped `single`, `pipeline`, and `framework` best-of-three sweeps, renders
`DOCKER_BEST_OF_3_<run-id>.md`, and fails clearly if any cells are incomplete. Reuse the same
`BOF3_RUN_ID` to fill retryable infra/auth/liveness rows without losing prior valid attempts.
The runner defaults to the fixture's normal Compose project because these challenges pre-build images
under their default names. `--concurrency N` parallelizes across distinct benchmarks while each
benchmark's model combos remain serial. `docker compose up` is run with `--no-build` and a Docker
daemon preflight runs before any rows are appended, so Docker/Desktop failures fail fast instead of
turning into hundreds of duplicate infra rows. Benchmarks that declare fixed host `ports:` are
automatically serialized only against other jobs using the same host port; dynamic `ports: [80]`
fixtures still run in parallel. `--unique-compose-project` is an advanced mode for fixtures that
tolerate project-prefixed image names; otherwise use the default project mode. Codex cells default
to `--max-codex 1` because shared ChatGPT OAuth refresh tokens can race; pass `--max-codex 0` only
when using auth that is safe to refresh concurrently.
The preferred local verification after changing `pentestgpt_agent/` is
`make docker-bench-agent-quick` from the repo root. Defaults are
`AGENT_BENCH_TARGETS=XBEN-080-24`, `AGENT_BENCH_COMBOS=claude-sonnet`,
`AGENT_BENCH_CONCURRENCY=1`, `AGENT_BENCH_EXECUTOR_CONCURRENCY=2`, `AGENT_BENCH_TIMEOUT=1200`, and
`AGENT_BENCH_OUT=docker_framework_quick.jsonl`. The target uses a timestamped
`AGENT_BENCH_ATTEMPT` by default so repeated runs do not skip stale completed rows.
For a strictly apples-to-apples comparison, run each refreshed variant on the **same image digest** as the pipeline baseline
(`--image <ref>`; the digest + git commit are recorded per row). Useful env vars match the
host harness: `PILOT_CODEX_EFFORT` (default `medium`), `PILOT_COMBOS`, `XBEN_ROOT` (target checkout),
`DOCKER_IMAGE` (default `pentestgpt:latest`), and `PENTESTGPT_SOURCE_ROOT` (same as
`--source-root`).

**Scoring parity.** The pipeline runs in raw-streaming mode (assistant text only, no tool-result
bodies), so the single variant scores only the agent's *verbalized* text — claude `assistant` blocks
/ codex `agent_message` items — never raw tool output. The framework variant scores its generated
report plus final stdout for the same ground-truth flag. This keeps the head-to-head fair.

## Benchmark sets (toggleable) — `bench_set.py`

`benchmark_sets.json` defines **named challenge sets** you can flip on and off per
challenge, so you (or an agent) curate a set once and re-run it without editing code
or retyping `--benchmarks` lists. `bench_set.py` is a thin, agent-friendly wrapper
over `run_docker_bench.py`: it selects the enabled challenges, resolves `XBEN_ROOT`,
picks parallelism, and shells out. Docker is still triggered entirely inside the
runner (`make build` → `docker compose up` → discover target IP → `docker run` the
tool image → score → teardown).

The seed set is **`hard-open`**: all 8 hard (level-3) XBOW challenges plus 2
proven-solvable medium controls (`XBEN-001-24`, `XBEN-080-24`). Its `solved_by_framework`
flags record that only `XBEN-057-24` has ever fallen to `pentestgpt_agent`; the rest
are the framework's open hard problems (`XBEN-093-24` and the `Cross` XSS challenges
have known EOL-Debian/phantomjs build issues — expect to need
`DOCKER_DEFAULT_PLATFORM=linux/amd64` or an `archive.debian.org` apt pin first).

```bash
cd benchmark/pilot

# See a set and its on/off state (--json for machine parsing):
uv run python bench_set.py list --set hard-open
uv run python bench_set.py list --set hard-open --json

# Print just the enabled ids (composes with other tools/targets):
uv run python bench_set.py ids --set hard-open
#   -> feed the existing bestof3 suite:  make docker-bench-bestof3 BOF3_BENCHMARKS=$(uv run python bench_set.py ids)

# Toggle challenges (persists to benchmark_sets.json; 'all' targets every entry):
uv run python bench_set.py disable XBEN-057-24 XBEN-101-24     # drop the already-solved ones
uv run python bench_set.py enable XBEN-057-24

# Run the enabled challenges. --concurrency auto prints host facts and picks a
# conservative parallelism; pass a number to fix it. --dry-run shows the exact
# run_docker_bench.py command(s) without running anything.
uv run python bench_set.py run --set hard-open --variant framework --concurrency auto --dry-run
uv run python bench_set.py run --set hard-open --variant framework --concurrency auto
```

**Agent flow.** An agent typically: (1) `list --json` to read the set + toggle state,
(2) `enable`/`disable` to curate, (3) `run --concurrency auto` (or an explicit `N`) —
the tool prints CPU-core count and the enabled count so the agent can choose how many
benchmarks run in parallel. `--variant both` runs `single` then `framework`
sequentially. Results go to `docker_<variant>_<set>.jsonl` unless `--out` overrides.

**`XBEN_ROOT` resolution.** `bench_set.py` uses `--xben-root` → `$XBEN_ROOT` → a list
of known checkout paths, and errors clearly if none exist. (The hardcoded default in
`run_docker_bench.py` is a dead path; point `XBEN_ROOT` at a real
`xbow-engineering/validation-benchmarks` checkout of `XBEN-*-24` dirs.) It preflights
that every enabled challenge dir exists and refuses to run if any are missing (pass
`--allow-missing` to override); build failures still surface as `BUILD_ERROR` rows.

Make wrappers:

```bash
make docker-bench-set-list                          # show the default set (BENCH_SET=hard-open)
make docker-bench-set BENCH_SET_DRY_RUN=1           # print the plan + commands
make docker-bench-set BENCH_SET_COMBOS=claude-sonnet BENCH_SET_CONCURRENCY=2
# Knobs: BENCH_SET, BENCH_SET_VARIANT{framework|single|both}, BENCH_SET_CONCURRENCY{auto|N},
#        BENCH_SET_COMBOS, BENCH_SET_TIMEOUT, BENCH_SET_ATTEMPTS, BENCH_SET_MAX_CODEX, BENCH_SET_XBEN_ROOT
```

## How the host-loopback harness works

1. **Build** — `make build` in the challenge dir. This bakes the ground-truth flag
   `FLAG{sha256(UPPERCASE-DIRNAME)}` into the image (per the benchmarks' `common.mk`). This is the
   flag the harness greps for — *not* the UUID in each dir's `.env` (which `make` overrides).
2. **Up** — a *fresh* `docker compose up -d --wait` per model run (clean state per run).
3. **Discover** — parse `docker compose ps --format json` for the loopback `PublishedPort`
   (skipping the `:3306` MySQL side-car); target URL = `http://127.0.0.1:<port>`.
4. **Run** — `pentestgpt --target <url> --backend <b> --model <m> --no-telemetry` with a timeout, in
   an isolated workspace (`WORKING_DIRECTORY` per run). `PENTESTGPT_BENCH=1` makes the Codex backend
   emit a greppable `[CODEX_USAGE]` token line.
5. **Judge** — success iff the ground-truth flag appears (case-insensitive) in captured stdout. This
   is identical for both runtimes (the agent must *verbalize* the flag; raw mode does not echo
   tool-result bodies), keeping the comparison fair.
6. **Teardown** — `docker compose down --remove-orphans -v`.

Statuses: `SOLVED` / `UNSOLVED` / `TIMEOUT` / `ERROR` (tool/agent error) / `BUILD_ERROR`. Build/boot
failures are classified as **infrastructure** and excluded from solve-rate denominators by `report.py`.

---

## Current status

### Docker-network baseline

`DOCKER_REPORT.md` is the current comparable baseline. It covers **10 representative medium/hard
targets** (8 level-2, 2 level-3) across all four model/runtime combinations: **40 Docker-network
runs** total. The xbow target stack ran via Docker Compose; the PentestGPT tool container joined the
target Docker network and attacked the target container IP directly (`172.x`), not a host-loopback
published port.

| Model | Solved | Solve rate | Avg solved time | Accounting |
|---|---:|---:|---:|---|
| Codex `gpt-5.5` | 7/10 | 70% | 424s | 11,589,909 tokens |
| Claude Sonnet | 6/10 | 60% | 458s | $1.83 captured |
| Claude Opus | 5/10 | 50% | 304s | $5.97 captured |
| Codex `gpt-5.4-mini` | 3/10 | 30% | 427s | 10,181,137 tokens |

The Docker baseline was run against git commit `dca0019` and image digest
`sha256:0c4c0f3e319bff7fc83996876fbfe143b1fae3455db6c2aa4a24117d88c893f5`.

### Single-agent and framework comparison

`DOCKER_COMPARISON.md` joins the 10-target pipeline baseline with the pure single-agent records and
the current framework smoke result. As of the latest refresh:

- Pure single-agent records cover the same 10 targets × 4 model/runtime combinations.
- The framework variant has a live Docker-network smoke row for `XBEN-080-24` with Claude Sonnet:
  `SOLVED` in 385.2s, `completed=True`, and a judge-accepted report containing the exact flag.
  That run used `pentestgpt:latest` for tools plus `--source-root` to mount this checkout at `/app`.

### Host-loopback pilot

`REPORT.md` is kept for historical comparison. That **13-challenge × 4-model pilot** was halted early
when scans tripped host endpoint-security monitoring. **47 of 52** runs completed; **8** challenges
were runnable; **6** were fully covered by all four models. Fully-covered headline: Codex `gpt-5.5`
5/6, Claude Opus 3/6, Claude Sonnet 2/6, Codex `gpt-5.4-mini` 2/6.

---

## Remaining tasks

- [x] **Comparable Docker baseline** — 10 representative L2/L3 targets × 4 models, container-to-container.
- [x] **Reusable Docker-network runner** — `run_docker_bench.py` supports `single`, `pipeline`, and
      `framework` variants with resumable JSONL output.
- [x] **Safe default-project parallelism** — `--concurrency N` now runs distinct benchmarks in
      parallel without `--unique-compose-project`, uses `docker compose up --no-build`, preflights
      Docker, serializes overlapping fixed host ports, and keeps Codex at `--max-codex 1` by default.
- [x] **Quick framework verification target** — `make docker-bench-agent-quick` runs the default
      local `pentestgpt_agent` Docker-network smoke for code-change validation.
- [x] **Final best-of-3 wrapper** — `make docker-bench-bestof3` runs the 10-target comparison suite
      with canary, timestamped outputs, report generation, and completion validation.
- [ ] **Full-sweep Makefile ergonomics** — add a separate full-59-target wrapper and map a
      conservative `JOBS` knob to runner `--concurrency`.
- [ ] **Full medium/hard sweep** — all 59 challenges (51 L2 + 8 L3) × 4 models.
- [ ] **arm64 infra fixes** — `mysql:5.7` has no arm64 manifest (XBEN-040/078); several XSS images
      are EOL Debian-buster/phantomjs (apt 404: XBEN-091/093/100). Fix with `DOCKER_DEFAULT_PLATFORM=linux/amd64`
      emulation, a `mariadb` swap, or an `archive.debian.org` apt pin; else document as excluded.
- [ ] **Cost accounting** — Claude `$` is only captured on a clean `[DONE]`; solved-but-timed-out
      runs report $0. Add a Codex token→$ estimate for cross-model comparability.
- [ ] **Execute final best-of-3 results** — run `make docker-bench-bestof3` on the 10-target suite
      and commit or archive the generated timestamped report.
- [ ] **Codex effort sweep** — currently pinned `medium`; compare low/medium/high.
- [ ] **Tests/CI** — `CodexBackend` translation has unit coverage; still wire `pentestgpt_agent/` +
      `unified_agent/` into Makefile lint/typecheck.

---

## Docker-network execution model

**Problem.** The agents must perform aggressive scanning/exploitation to solve CTFs, and on a
monitored workstation that traffic (a) trips host endpoint-security and (b) hits arch-specific build
failures. We want to run the *entire* 59-challenge × 4-model sweep unattended, isolated from host
monitoring, and reproducibly.

**Key insight.** The host-loopback harness publishes each target to host loopback
(`127.0.0.1:<port>`) and runs the agent on the host, so scan traffic crosses **host** endpoints that
EDR watches. The Docker-network harness instead discovers the target container's internal
Docker-network IP and points the tool container at that URL. The fixture may still publish an
ephemeral or fixed host port because the original Compose files say so, but the benchmark agent does
not attack that host-loopback URL.

### Current architecture

- **Host-driven orchestration.** `run_docker_bench.py` runs on the host and talks to the host Docker
  daemon. It does not mount `docker.sock` into a long-lived worker container.
- **One tool container per cell.** Each active `(attempt, benchmark, combo, variant)` gets a fresh
  `pentestgpt:latest` container, a unique workspace under `/tmp/pgpt_docker_ws`, and a unique log row.
- **Target by internal URL.** The runner parses `docker compose ps` and `docker inspect` to find the
  non-database service's Docker network and internal IP/port, then runs the tool container on that
  network.
- **Persisted auth volumes.** `pentestgpt-claude` and `pentestgpt-codex` are mounted into the tool
  container. Claude can run concurrently; Codex is capped by default because shared ChatGPT refresh
  tokens can race.
- **Durable results.** JSONL outputs, reports, and logs stay under `benchmark/pilot/` so interrupted
  runs can resume and infra rows remain auditable.

### Parallel execution policy

The current runner parallelizes at the **benchmark worker** level. One active cell is
`(attempt, benchmark, combo, variant)`: bring up one fresh target stack, attach one fresh PentestGPT
tool container, write one log/result row, then tear everything down.

Current implementation rules:

- Use the fixture's **default Compose project** for normal runs. XBOW builds images under those
  default project names, so a synthetic `-p pgpt-...` name can make Compose look for different image
  tags. The runner uses `docker compose up --no-build`; if images are missing, the row fails fast
  instead of rebuilding or destabilizing Docker Desktop.
- `--concurrency N` runs distinct benchmark directories in parallel. Combos inside one benchmark stay
  serial, so the same default Compose project is never attacked by two agents at once.
- Fixed host `ports:` are detected from Compose and overlapping ports are serialized. Dynamic ports
  such as `ports: [80]` can run in parallel because Docker chooses an ephemeral host port.
- `--unique-compose-project` is an advanced escape hatch for fixtures that have explicit image names
  or generated image-only Compose files. Do not enable it for the normal XBOW sweep unless you have
  confirmed the target starts with `--no-build`.
- Claude cells can share the `pentestgpt-claude` volume. Codex cells default to `--max-codex 1`
  because ChatGPT OAuth refresh tokens rotate; only pass `--max-codex 0` with auth that is safe under
  concurrent refresh.
- Resumability keys completed rows on `(benchmark_id, combo, variant, attempt)`. Infra/auth/liveness
  rows remain in the JSONL log for diagnosis but do not block a later retry of the same cell.

### Why this satisfies the security constraint

Endpoint-security on the host watches the host's own endpoints/processes. With the tool container
attacking the target's internal Docker-network URL, scan/exploit packets stay on the Docker bridge
instead of being directed at `127.0.0.1`. The original fixture may still expose a host port for
health checks or manual debugging, but the benchmark traffic is container-to-container. For stricter
network isolation, the next hardening step is generated image-only/no-host-port Compose; for full
process isolation, run the whole stack on a dedicated benchmarking VM/host with no endpoint monitor.

### Incremental path

1. **Use the current Docker-network runner.** Start with a two-target smoke at `--concurrency 2`.
   Scale to the 10-target baseline matrix, then the medium/hard sweep.
2. **Add a Makefile wrapper.** Wrap the runner, standard output paths, `PILOT_COMBOS`, `--attempts`,
   `--concurrency`, and `--max-codex` into a documented `make docker-bench` command.
3. **Generate image-only/no-host-port Compose only if needed.** This is useful for same-benchmark
   concurrent combos or stricter network isolation, but it is not required for the current
   benchmark-level parallelism.
4. **Run on a dedicated benchmark host/VM for large sweeps.** This keeps Docker Desktop resource
   pressure and local endpoint-security noise out of the measurement.

### Caveats

- Model CLIs still need outbound HTTPS to the provider — ensure the agent container's egress NIC is
  allowed and not itself flagged.
- Socket-mount shares the host daemon (targets run under host `dockerd`); network isolation still
  holds, but for strict process isolation prefer DinD or a dedicated VM.
- Emulated amd64 targets are slower → raise timeouts; size concurrency for the host
  (each slot ≈ one agent container + one target stack).

**Near-term implementation effort:** the runner is already in place. Remaining engineering work is
mostly wrapper/report ergonomics plus optional generated no-host-port Compose for stricter isolation.

> **Full development plan** (image build, the hard part — persistent Claude **and** Codex login so you
> install + log in once and never again — networking, Make targets, phased milestones):
> [`docs/docker-dev-plan.md`](../../docs/docker-dev-plan.md).
