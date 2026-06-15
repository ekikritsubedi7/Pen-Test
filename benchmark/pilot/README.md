# PentestGPT multi-model benchmark results

This directory tracks the **autonomous PentestGPT CTF pipeline** against the
[xbow-engineering/validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks).
It contains the original host-loopback harness plus the current Docker-network baseline, comparing
four model/runtime combinations driven through the *same* pipeline:

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
| `docker_results.jsonl` | Source-of-truth records for the completed Docker-network baseline. |
| `DOCKER_REPORT.md` | Current comparable Docker-network baseline report. |
| `docker_logs/<challenge>__<combo>.log` | Full captured stdout per Docker-network run. |
| `selected.json` | The challenge set used for the last run. |

## Prerequisites

- Docker (running), `make`, `openssl`, `curl`.
- The xbow fixtures checked out locally (a separate `xbow-validation-benchmarks` checkout). Set the
  path at the top of `run_pilot.py` (`BENCH_ROOT`).
- Authenticated `claude` CLI and `codex` CLI on `PATH` (`claude` logged in; `codex login`).
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
is the committed Docker-network baseline; productizing its runner/renderer into this directory is
listed under remaining tasks.

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

### Host-loopback pilot

`REPORT.md` is kept for historical comparison. That **13-challenge × 4-model pilot** was halted early
when scans tripped host endpoint-security monitoring. **47 of 52** runs completed; **8** challenges
were runnable; **6** were fully covered by all four models. Fully-covered headline: Codex `gpt-5.5`
5/6, Claude Opus 3/6, Claude Sonnet 2/6, Codex `gpt-5.4-mini` 2/6.

---

## Remaining tasks

- [x] **Comparable Docker baseline** — 10 representative L2/L3 targets × 4 models, container-to-container.
- [ ] **Productize the Docker-network harness** — commit an in-repo `make docker-bench`/script instead
      of relying on the one-off operational harness used for `DOCKER_REPORT.md`.
- [ ] **Full medium/hard sweep** — all 59 challenges (51 L2 + 8 L3) × 4 models.
- [ ] **arm64 infra fixes** — `mysql:5.7` has no arm64 manifest (XBEN-040/078); several XSS images
      are EOL Debian-buster/phantomjs (apt 404: XBEN-091/093/100). Fix with `DOCKER_DEFAULT_PLATFORM=linux/amd64`
      emulation, a `mariadb` swap, or an `archive.debian.org` apt pin; else document as excluded.
- [ ] **Cost accounting** — Claude `$` is only captured on a clean `[DONE]`; solved-but-timed-out
      runs report $0. Add a Codex token→$ estimate for cross-model comparability.
- [ ] **Multi-attempt (best-of-k)** — the Dec-2025 baseline showed flaky timeouts recover on retry;
      single-shot solve rates are a lower bound.
- [ ] **Codex effort sweep** — currently pinned `medium`; compare low/medium/high.
- [ ] **Tests/CI** — `CodexBackend` translation has unit coverage; still wire `pentestgpt_agent/` +
      `unified_agent/` into Makefile lint/typecheck.

---

## Docker-network execution model

**Problem.** The agents must perform aggressive scanning/exploitation to solve CTFs, and on a
monitored workstation that traffic (a) trips host endpoint-security and (b) hits arch-specific build
failures. We want to run the *entire* 59-challenge × 4-model sweep unattended, isolated from host
monitoring, and reproducibly.

**Key insight.** The host-loopback harness publishes each target to host loopback (`127.0.0.1:<port>`) and
runs the agent on the host — so all scan traffic crosses **host** endpoints that EDR watches. If
instead the **agent and the target sit on the same internal Docker bridge with no host-published
ports**, the scan/exploit traffic is container→container on an isolated network and never touches a
host endpoint. The only traffic leaving is the model-API HTTPS calls (ordinary, allowed egress).

The current 10-target Docker baseline used the core of this design: the target stack ran in Docker,
the tool ran in `pentestgpt:latest`, and the tool container joined the target Docker network so scan
traffic was container-to-container. The reusable in-repo command is still open work.

### Recommended architecture for the full sweep

```
┌──────────────────────────── benchmark host / dedicated VM ─────────────────────────────┐
│                                                                                          │
│   docker network: xben-bench-<id>  (--internal: NO route off-host) ── isolates scans     │
│        ┌──────────────┐                        ┌──────────────────────────────────┐      │
│        │ target stack │  ← nmap/gobuster/RCE → │ agent container                  │      │
│        │ (compose,    │   (container↔container)│  uv + pentestgpt + claude/codex  │      │
│        │  no host     │                        │  + nmap/gobuster/sqlmap/...      │      │
│        │  ports)      │                        │                                  │      │
│        └──────────────┘                        └───────────────┬──────────────────┘      │
│                                                                 │ 2nd NIC (egress-only)   │
│                                                       default bridge → NAT → internet     │
│                                                       (HTTPS to Anthropic / OpenAI only)  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Two networks per run.** Target compose stack attaches to an `--internal` bridge
  (`xben-bench-<id>`) with **no `ports:` published to the host** → unreachable from the host, scans
  stay on the bridge. The **agent container** attaches to *both* that internal bridge (to reach the
  target by service name/IP) **and** a normal NAT bridge used *only* for model-API egress.
- **Agent runs in a container**, not on the host — so its tool processes and scan traffic are
  contained. Reuse the existing `pentestgpt:latest` image, which already has the pipeline, Claude CLI,
  Codex CLI, `uv`, and the core pentest toolchain.
- **Orchestrator** mounts the host Docker socket (`/var/run/docker.sock`) — simplest — or true DinD
  for full nesting. It loops challenges exactly like `run_pilot.py` but creates the per-run internal
  network + connects the agent container instead of publishing ports.
- **Auth** mounted into the agent container through the persisted login volumes
  (`pentestgpt-claude`, `pentestgpt-codex`) so the CLIs are logged in non-interactively and can refresh
  tokens.
- **Arch** uniform via `DOCKER_DEFAULT_PLATFORM=linux/amd64` (Rosetta/qemu emulation) so `mysql:5.7`
  and friends build/run everywhere; bump per-run timeout to absorb emulation slowdown.
- **Persistence** — keep `benchmark/pilot/*results.jsonl`, reports, and logs on the host so results
  survive and the run stays resumable.

### Why this satisfies the security constraint

Endpoint-security on the host watches the host's own endpoints/processes. With targets on an
`--internal` bridge and **no published host ports**, the scan/exploit packets are confined to the
Docker bridge — they never appear on `127.0.0.1` or a host NIC, so the host EDR doesn't observe
benchmark scanning. For *full* process-level isolation as well, run the whole stack on a **dedicated
benchmarking VM/host** (no corporate EDR), which the Docker design ports to unchanged.

### Incremental path (lowest effort first)

1. **VM-first (zero code).** Run the existing host `run_pilot.py` on a dedicated throwaway VM/cloud
   box with `DOCKER_DEFAULT_PLATFORM=linux/amd64`. Solves both monitoring and arch immediately;
   good enough to get the full table.
2. **Containerize the agent** (`benchmark/docker/Dockerfile.agent`) and switch the harness to
   internal-network + no-published-ports + connect-agent-container. Portable and reproducible.
3. **One-command sweep** (`benchmark/docker/run.sh` / compose) bundling build of the agent image,
   the loop over all 59 challenges × 4 models, and report generation — runnable on a CI box.

### Caveats

- Model CLIs still need outbound HTTPS to the provider — ensure the agent container's egress NIC is
  allowed and not itself flagged.
- Socket-mount shares the host daemon (targets run under host `dockerd`); network isolation still
  holds, but for strict process isolation prefer DinD or a dedicated VM.
- Emulated amd64 targets are slower → raise timeouts; size concurrency for the host
  (each slot ≈ one agent container + one target stack).

**Estimated effort:** path 1 ≈ minutes (just a VM); path 2 ≈ half a day (agent image + ~40 lines of
network wiring in the harness); path 3 ≈ another half day (packaging + a clean full-sweep run).

> **Full development plan** (image build, the hard part — persistent Claude **and** Codex login so you
> install + log in once and never again — networking, Make targets, phased milestones):
> [`docs/docker-dev-plan.md`](../../docs/docker-dev-plan.md).
