# PentestGPT multi-model benchmark harness

Host-based harness that measures the **autonomous PentestGPT CTF pipeline** against the
[xbow-engineering/validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks),
comparing four model/runtime combinations driven through the *same* pipeline:

| Combo | Runtime | Model id | Billing |
|---|---|---|---|
| Claude Opus | Claude Code CLI (`claude -p`) | `opus` | API $ |
| Claude Sonnet | Claude Code CLI (`claude -p`) | `sonnet` | API $ |
| Codex gpt-5.5 | OpenAI Codex (`app-server` SDK) | `gpt-5.5` | ChatGPT sub (tokens) |
| Codex gpt-5.4-mini | OpenAI Codex (`app-server` SDK) | `gpt-5.4-mini` | ChatGPT sub (tokens) |

This was enabled by making the pipeline backend-pluggable: `pentestgpt --backend {claude,codex}`
(`CodexBackend` in `pentestgpt/core/backend.py`).

> ⚠️ **Safety / authorization.** The agents run *real* offensive tooling (nmap, gobuster, nikto,
> sqlmap, command-injection / deserialization RCE payloads) against the benchmark targets. Run this
> **only** where that is authorized and where it will not trip local endpoint-security monitoring.
> A pilot run on a monitored workstation was halted mid-sweep for exactly this reason — which is the
> motivation for the [Dockerized isolated run](#proposal-run-the-whole-sweep-in-docker) below.

---

## Files

| File | Purpose |
|---|---|
| `run_pilot.py` | Orchestrator: build → up → port-discover → run agent(s) → flag-check → teardown. Resumable. |
| `report.py` | Renders `REPORT.md` (per-challenge × per-model table + aggregates) from `results.jsonl`. |
| `results.jsonl` | One JSON record per `(challenge, model)` run. Source of truth; re-run skips completed pairs. |
| `logs/<challenge>__<combo>.log` | Full captured stdout per run. |
| `REPORT.md` | Generated report. |
| `selected.json` | The challenge set used for the last run. |

## Prerequisites

- Docker (running), `make`, `openssl`, `curl`.
- The xbow fixtures checked out locally (a separate `xbow-validation-benchmarks` checkout). Set the
  path at the top of `run_pilot.py` (`BENCH_ROOT`).
- Authenticated `claude` CLI and `codex` CLI on `PATH` (`claude` logged in; `codex login`).
- `uv sync` in the repo root.

## Usage

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

## How it works

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

A **13-challenge × 4-model pilot** was run (not the full 59 medium/hard set), then halted early when
its scans tripped host endpoint-security monitoring. **47 of 52** runs completed; **8** challenges were
runnable, **6** fully covered by all four models. See `REPORT.md` for the table. Headline
(fully-covered subset): Codex `gpt-5.5` 5/6 · Claude Opus 3/6 · Claude Sonnet 2/6 · Codex `gpt-5.4-mini` 2/6.

---

## Remaining tasks

- [ ] **Full medium/hard sweep** — all 59 challenges (51 L2 + 8 L3) × 4 models. Only a 13-challenge
      pilot ran.
- [ ] **Dockerized / isolated execution** — see the proposal below; the gating blocker for a full
      run on a monitored host.
- [ ] **arm64 infra fixes** — `mysql:5.7` has no arm64 manifest (XBEN-040/078); several XSS images
      are EOL Debian-buster/phantomjs (apt 404: XBEN-091/093/100). Fix with `DOCKER_DEFAULT_PLATFORM=linux/amd64`
      emulation, a `mariadb` swap, or an `archive.debian.org` apt pin; else document as excluded.
- [ ] **Cost accounting** — Claude `$` is only captured on a clean `[DONE]`; solved-but-timed-out
      runs report $0. Add a Codex token→$ estimate for cross-model comparability.
- [ ] **Multi-attempt (best-of-k)** — the Dec-2025 baseline showed flaky timeouts recover on retry;
      single-shot solve rates are a lower bound.
- [ ] **Codex effort sweep** — currently pinned `medium`; compare low/medium/high.
- [ ] **Tests/CI** — unit test for the `CodexBackend` event→`AgentMessage` translation; wire
      `pentestgpt_agent/` + `unified_agent/` into Makefile lint/typecheck.

---

## Proposal: run the whole sweep in Docker

**Problem.** The agents must perform aggressive scanning/exploitation to solve CTFs, and on a
monitored workstation that traffic (a) trips host endpoint-security and (b) hits arch-specific build
failures. We want to run the *entire* 59-challenge × 4-model sweep unattended, isolated from host
monitoring, and reproducibly.

**Key insight.** Today the harness publishes each target to host loopback (`127.0.0.1:<port>`) and
runs the agent on the host — so all scan traffic crosses **host** endpoints that EDR watches. If
instead the **agent and the target sit on the same internal Docker bridge with no host-published
ports**, the scan/exploit traffic is container→container on an isolated network and never touches a
host endpoint. The only traffic leaving is the model-API HTTPS calls (ordinary, allowed egress).

### Recommended architecture

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
  contained. Reuse/extend the existing `pentestgpt:latest` image (already has the pentest toolchain);
  add the `codex` CLI + `openai_codex` SDK + `uv`.
- **Orchestrator** mounts the host Docker socket (`/var/run/docker.sock`) — simplest — or true DinD
  for full nesting. It loops challenges exactly like `run_pilot.py` but creates the per-run internal
  network + connects the agent container instead of publishing ports.
- **Auth** mounted read-only into the agent container: `~/.claude`, `~/.codex` (or `ANTHROPIC_API_KEY`/
  ChatGPT creds) so the CLIs are logged in non-interactively.
- **Arch** uniform via `DOCKER_DEFAULT_PLATFORM=linux/amd64` (Rosetta/qemu emulation) so `mysql:5.7`
  and friends build/run everywhere; bump per-run timeout to absorb emulation slowdown.
- **Persistence** — bind-mount `benchmark/pilot/{results.jsonl,logs,REPORT.md}` out of the runner so
  results survive and the run stays resumable.

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
