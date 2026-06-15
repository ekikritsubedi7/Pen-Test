# Development plan — run the whole PentestGPT pipeline in Docker

**Goal.** One reproducible Docker image that contains the full PentestGPT solution; a user
**installs once**, does a **one-time interactive login for both Claude Code and Codex**, and from then
on can repeatedly: spawn a container → run the pipeline against an xbow target (any model / pipeline /
mode) → collect results — **without ever logging in again**.

This plan follows the *existing* build patterns (the `Dockerfile` + `docker-compose.yml` +
`scripts/entrypoint.sh` + Makefile already in the repo) and extends them; it does not start from scratch.

---

## Implementation status (2026-06-15)

**The tool image, persistent dual-login flow, Docker run target, and a 10-target Docker-network
benchmark baseline are built and verified.** The benchmark harness is still intentionally outside the
image: the image is the tool; the benchmark drives it from the host or a dedicated benchmark runner.

- ✅ **Phase 1 — image.** Dockerfile extended: Codex CLI (`@openai/codex`), the missing wheel packages
  (`unified_agent`/`pentestgpt_agent`/`pentestgpt_legacy`), `gobuster`/`dirb`, a `.codex` auth dir, and
  the auth-status helper. Verified in-image: `claude 2.1.177`, `codex 0.139.0`, `uv`, `pentestgpt --help`,
  `import openai_codex`, `--backend {claude,codex}`. `.dockerignore` keeps creds/benchmark/workspace out.
- ✅ **Phase 2 — dual-auth persistence.** `codex-config` volume + pinned volume names
  (`pentestgpt-claude`/`pentestgpt-codex`); an **idempotent** `scripts/docker-login.sh` that
  *checks logins first (live) and only logs in the missing one(s)*; `scripts/docker-auth-status.sh`;
  entrypoint token-export + preflight; Make targets. The auth design is **asymmetric by token model**
  (see §3): **Claude** → `setup-token` long-lived token stored in the volume, exported as
  `CLAUDE_CODE_OAUTH_TOKEN`; **Codex** → its **own** in-container `codex login` (NOT seeding — ChatGPT
  refresh tokens are single-use, so a shared/copied login 401s on first refresh), with the
  `localhost:1455` OAuth callback forwarded in via a `socat` hop. **Verified live:** after one
  `make docker-login`, a fresh container reports `claude: logged in` and `codex: logged in` with real
  1-token round-trips, and persists across recreation with no re-login.
- ✅ **Phase 3 — run.** `make docker-run`. **Verified end-to-end:** the dockerized tool ran the full CTF
  pipeline (Codex) against an isolated fixture (internal docker bridge, no host ports) and **captured the
  flag** with no sandbox/exec errors; the pentest pipeline ran all stages cleanly too — both backends
  authenticate from the persisted volumes.
- ✅ **Phase 4 — Docker-network benchmark execution.** A 10-target xbow baseline completed with the tool
  container joined to each target's Docker network and attacking the target container IP directly.
  Results: `benchmark/pilot/DOCKER_REPORT.md` and `benchmark/pilot/docker_results.jsonl`.
- ◐ **Phase 5 — reusable benchmark command.** The Docker-network baseline is complete, but the operational
  harness is not yet committed as a reusable `make docker-bench`/script. Productizing that runner and
  expanding to the full 59-target medium/hard sweep remain open.
- ◐ **Phase 6 — Docs/CI.** README, `CLAUDE.md`, benchmark docs, and this plan are being kept in sync.
  A gated login-persistence CI test and broader Makefile lint/typecheck coverage remain open.

---

## 1. Where things stand today (verified)

| Piece | Current state | Remaining gap |
|---|---|---|
| `Dockerfile` | Ubuntu 24.04 + Python 3.12 + pentest tools (`nmap`, `gobuster`, `dirb`, `ripgrep`, etc.) + Node 20 + Claude CLI + Codex CLI + `uv`; installs `pentestgpt/`, `unified_agent/`, `pentestgpt_agent/`, and `pentestgpt_legacy/`. Non-root `pentester`. | Benchmark harness and Docker CLI are not in the image by design; full scanner set (`sqlmap`, `nikto`, `ffuf`) is still optional/open. |
| `docker-compose.yml` | Persists Claude, Codex, and CCR config through explicit named volumes (`pentestgpt-claude`, `pentestgpt-codex`, `ccr-config`); exposes `host.docker.internal`; keeps `NET_ADMIN` for VPN workflows. | No benchmark compose profile or results/fixtures mounts yet. |
| `scripts/entrypoint.sh` | Supports `openrouter`, `local`, `anthropic`, and `manual`; loads persisted Claude OAuth token; reports Claude/Codex auth status in manual mode. | Preflight is advisory today; it warns instead of hard-failing unauthenticated runs. |
| Makefile | Provides `docker-build`, `docker-login`, `docker-auth-status`, `docker-shell`, `docker-run`, `docker-down`, and `docker-nuke`. | No committed `docker-bench` or `docker-test-matrix` target yet. |
| Auth — **Claude** | macOS host → **Keychain** (not a portable file). Linux container → `~/.claude/.credentials.json` (file). `claude setup-token` issues a long-lived token via **code-paste** (no localhost callback). | First login must happen **inside** the container (mac creds can't be copied); then persisted by `claude-config`. |
| Auth — **Codex** | Container performs its own `codex login`; the `localhost:1455` OAuth callback is forwarded into the container via `socat`; session persists in the `pentestgpt-codex` volume. | API-key fallback is documented but not part of the default Make flow. |
| Backend wiring | `pentestgpt --backend {claude,codex}` already implemented (`pentestgpt/core/backend.py`). | — |
| Benchmark harness | Host-loopback harness remains in `benchmark/pilot/run_pilot.py`; Docker-network baseline results are committed in `DOCKER_REPORT.md`/`docker_results.jsonl`. | Commit/reuse the Docker-network runner as an in-repo command and scale beyond the 10-target baseline. |

**Design driver:** the only genuinely hard problem is **persisting two independent login sessions**.
Everything else is packaging. The two auth systems behave differently, so they get different (but
symmetric) handling, both ending in a **named volume** so login survives container recreation.

---

## 2. Success criteria (Definition of Done)

| Criterion | Status |
|---|---|
| `make docker-build` produces an image with the full solution + both CLIs + the core pentest toolchain. | Done |
| `make docker-login` leaves both Claude and Codex authenticated in persistent volumes; later containers need no login. | Done and live-verified with `make docker-auth-status`. |
| `make docker-run TARGET=... BACKEND=... MODEL=... MODE=...` runs the pipeline from the container. | Done. |
| Docker-network benchmark execution avoids host-loopback target URLs. | Done for the 10-target baseline in `DOCKER_REPORT.md`. |
| `make docker-bench` runs the multi-model benchmark harness end-to-end and produces a report. | Open: the operational Docker harness worked but is not yet committed/productized. |
| A gated login-persistence test proves auth survives down/recreate. | Open: manual/live verification exists; CI test remains. |
| Full 59-target medium/hard xbow sweep. | Open. Current Docker baseline is 10 targets. |

---

## 3. The hard part — persistent dual login (detailed design)

### 3.1 Principle
Each CLI writes its credentials to a directory we mount as a **named Docker volume**. First-time login
populates the volume; the CLIs **auto-refresh** their OAuth tokens and write back to the same files, so
the session stays valid across restarts. We never bake secrets into the image and never require login
twice.

```
volumes:
  claude-config  ->  /home/pentester/.claude     # Claude: oauth_token (from setup-token) + config
  codex-config   ->  /home/pentester/.codex       # Codex: auth.json (own login) + config.toml
```

> **Key lesson (implemented):** the two CLIs have *different token models*, so they need *different*
> handling. Claude's `setup-token` is a long-lived static token (safe to store/share); Codex (ChatGPT)
> uses **single-use rotating refresh tokens** (copying/sharing a login breaks on first refresh). The
> final design reflects this asymmetry.

### 3.2 Claude Code — `setup-token`, store the token in the volume
- Run `claude setup-token` in the container (interactive: open the printed URL, approve in the host
  browser; a **code-paste** flow, **no port forwarding**). It prints a **long-lived (1-year) token**.
- `setup-token` does **not** write `~/.claude/.credentials.json` — it's meant for headless use via
  `CLAUDE_CODE_OAUTH_TOKEN`. So `make docker-login` captures the token (read hidden, piped via stdin —
  never echoed) and stores it at `~/.claude/oauth_token` in the `claude-config` volume.
- The **entrypoint** exports `CLAUDE_CODE_OAUTH_TOKEN` from that file on every run, so `claude`
  authenticates non-interactively. (`PENTESTGPT_AUTH_MODE=manual` drops `ANTHROPIC_API_KEY` so the
  token is used.) macOS host creds live in the Keychain and can't be copied, so in-container
  `setup-token` is the portable, always-works path.

### 3.3 Codex — its **own** in-container login (no seeding), callback forwarded via socat
- **Do NOT seed/copy** `~/.codex/auth.json` from the host. ChatGPT refresh tokens are **single-use**:
  once either the host or the container refreshes, the other's copy is invalidated
  (`refresh token was already used`, 401). `codex login status` still says "logged in" (it only checks
  the local file), but the live call fails — a silent trap.
- Instead the container does its **own** `codex login` (a separate session, its own token lineage).
- `codex login` serves its OAuth callback on **`127.0.0.1:1455` inside the container**, which a plain
  `-p` publish can't reach. So the login container publishes `-p 1455:8455` and runs a **`socat` hop**
  (`TCP-LISTEN:8455 → TCP:127.0.0.1:1455`); the host browser's redirect to `localhost:1455` then lands
  on Codex inside the container. (Verified: `localhost:1455` → in-container `127.0.0.1:1455` returns 200.)
- API-key alternative (not ChatGPT sub): `printenv OPENAI_API_KEY | codex login --with-api-key`.

### 3.4 Idempotent login — check first, log in only what's missing
`make docker-login` first does a **live** round-trip check per CLI against the volumes (a present-but-
stale token correctly counts as "not logged in"), prints the status, and **only runs the login flow for
the one(s) that fail** — then re-verifies. Re-running it when both are valid is a no-op
("nothing to do"). `make docker-nuke` removes the volumes to force a full re-login (e.g. to rotate a token).

### 3.5 Token lifetime & refresh (operational notes)
- Both CLIs refresh OAuth tokens automatically and rewrite the files in the volumes → staying logged
  in across restarts is the default.
- Long idle gaps can still expire a refresh token; the entrypoint **preflight** detects an
  unauthenticated state and prints a clear "run `make docker-login`" message instead of failing deep
  in a run.
- Secrets hygiene: volumes hold tokens; document that they are as sensitive as a logged-in laptop.
  `.dockerignore` must exclude `.env*`, `~/.claude`, `~/.codex`, `workspace/`, `runs/` from the build
  context so nothing leaks into image layers.

---

## 4. Image design (implemented shape)

The image is the tool runtime, not the benchmark runner:

1. **Agent runtimes** — Claude CLI and Codex CLI are installed for the `pentester` user and available on
   `PATH`.
2. **Python packages** — the wheel includes `pentestgpt/`, `unified_agent/`, `pentestgpt_agent/`, and
   `pentestgpt_legacy/`, so the fixed pipeline, substrate, next-gen framework, and legacy CLI import in
   the container.
3. **Pentest toolchain** — the image includes `nmap`, `gobuster`, `dirb`, `netcat`, `curl`, `jq`,
   `ripgrep`, DNS/network utilities, OpenVPN, and tmux. `sqlmap`, `nikto`, `ffuf`, and large wordlists
   are still optional future additions.
4. **Auth helpers** — `entrypoint.sh` exports the persisted Claude OAuth token and reports Claude/Codex
   auth status; `docker-auth-status.sh` can also do optional live round-trips.
5. **Out of image by design** — `benchmark/`, credentials, workspace state, run artifacts, and caches
   are excluded by `.dockerignore`. The benchmark runner drives `pentestgpt:latest` from outside.
6. **Compatibility** — keep the non-root `pentester` user, CCR support, and `/workspace` default
   working directory for backward compatibility.

> Multi-stage optional later for size; not required for v1.

---

## 5. Targets, networking & results

The agent must reach the xbow target but **not** trip host endpoint monitoring (the reason a prior host
run was halted). Two modes matter:

- **Mode A — Docker-network target access (recommended and baseline-tested).** The harness brings up
  each xbow stack with Docker Compose, starts the PentestGPT tool container on the target's Docker
  network, discovers the target container IP, and points the agent at `http://172.x.x.x:<port>`.
  `DOCKER_REPORT.md`/`docker_results.jsonl` use this mode for all 40 records.
- **Mode B — simple loopback (legacy host harness).** Targets publish to loopback and the host agent
  uses `http://127.0.0.1:<port>`. Easier, but scans cross host endpoints; use only on an isolated
  host/VM.

**Docker-driving-Docker:** the current operational harness ran on the host and used the host Docker
daemon to build/compose targets and run tool containers. A future in-repo `docker-bench` runner can
either keep that host-orchestrated shape (simplest) or run inside a controller container with the Docker
socket mounted. **Results & fixtures:** keep `benchmark/pilot/*results.jsonl`, reports, and logs on the
host so runs are resumable and reviewable.

---

## 6. UX — Make targets (mirror existing patterns)

```
make docker-build         # docker compose build (image with both CLIs + full solution)
make docker-login         # ONE-TIME: interactive claude setup-token + codex login -> volumes
make docker-auth-status   # non-interactive check both CLIs are authed (used by CI + preflight)
make docker-shell         # interactive shell in the container (volumes attached)
make docker-run TARGET=http://… BACKEND=claude MODEL=opus MODE=ctf
make docker-down          # stop (KEEP volumes — stays logged in)
make docker-nuke          # stop + remove volumes (forces re-login) — explicit, separate target
```

Planned but not committed yet:

```
make docker-bench BENCHES=XBEN-001-24,… COMBOS=… TIMEOUT=540
make docker-test-matrix
```

Entrypoint has an auth preflight report: if `PENTESTGPT_AUTH_MODE=manual` and either CLI is
unauthenticated, it prints "run `make docker-login`" before the command starts. It currently warns
rather than hard-failing.

---

## 7. Multi-pipeline / multi-setting test matrix

The container must exercise *different settings with different pipelines*:

| Axis | Values |
|---|---|
| Pipeline | `pentestgpt` CTF mode · `pentestgpt` pentest mode · `pentestgpt_agent` framework (instructor/executor/judge) |
| Backend | `claude` · `codex` |
| Model | claude `opus`/`sonnet` · codex `gpt-5.5`/`gpt-5.4-mini` |
| Target | one xbow CTF challenge (flag) · the framework's local fixture (finding→report) |

A `make docker-test-matrix` runs a *small* representative sweep (e.g. 1 easy xbow challenge × the four
model combos in CTF mode, plus one `pentestgpt_agent` framework smoke) to prove every pipeline path
works in-container before any large benchmark run. The full benchmark sweep reuses
`benchmark/pilot/run_pilot.py` (already resumable + parametrized).

---

## 8. Implementation phases (with verification gates)

- **Phase 0 — Recon (done in this plan).** Auth layouts, login mechanisms, current Docker assets, gaps.
- **Phase 1 — Image.** Extend `Dockerfile`: codex CLI + `openai_codex` + `unified_agent`/
  `pentestgpt_agent`/`benchmark` + scanners + docker CLI + amd64 default. ✔ `docker build` succeeds;
  `claude --version`, `codex --version`, `uv run pentestgpt --help`, `python -c "import openai_codex"`.
- **Phase 2 — Dual-auth persistence (core).** Add `codex-config` volume; write `make docker-login`
  (claude `setup-token` + codex seed/login) and `make docker-auth-status`; entrypoint preflight.
  ✔ Login once → `down` → recreate (keep volumes) → `docker-auth-status` green → 1-token round-trips on
  both CLIs succeed with **no** re-login.
- **Phase 3 — Single run.** `make docker-run` against one xbow target (Mode B first). ✔ flag captured;
  results written to host.
- **Phase 4 — Docker-network target access.** ✔ 10-target xbow baseline completed with the tool
  container on the target Docker network and target URLs set to container IPs.
- **Phase 5 — Benchmark + matrix.** ◐ `DOCKER_REPORT.md` generated for 10 targets × 4 combos. Open:
  commit/productize the Docker-network harness as `make docker-bench`, add `make docker-test-matrix`,
  and run the full 59-target medium/hard sweep.
- **Phase 6 — Docs/CI.** ◐ Docs updated with the Docker baseline. Open: add a gated
  login-persistence test and broaden Makefile lint/typecheck coverage for `unified_agent/` and
  `pentestgpt_agent/`.

Each phase is independently verifiable; Phase 2 is the linchpin and is gated by the persistence test.

---

## 9. File-by-file change list

| File | Change |
|---|---|
| `Dockerfile` | Implemented: Codex CLI, Claude CLI, `unified_agent/`, `pentestgpt_agent/`, `pentestgpt_legacy/`, core pentest tools, and auth-status helper. Benchmark harness stays outside the image. |
| `docker-compose.yml` | Implemented: explicit Claude/Codex/CCR volumes shared with Make targets. Open: benchmark profile/results mounts. |
| `scripts/entrypoint.sh` | Implemented: persisted Claude token export and dual-auth status report; CCR/anthropic/manual modes kept. |
| `scripts/docker-login.sh` | Implemented: idempotent Claude `setup-token` + separate in-container Codex login with final live verification. |
| `scripts/docker-auth-status.sh` | Implemented: non-interactive auth status, optional `--roundtrip`. |
| `Makefile` | Implemented: `docker-build/login/auth-status/shell/run/down/nuke`. Open: `docker-bench` and `docker-test-matrix`. |
| `.dockerignore` | Implemented: excludes credentials, env files, workspace, benchmark artifacts, and caches from image layers. |
| `benchmark/pilot/run_pilot.py` | Host-loopback harness remains; Docker-network baseline was produced by an operational external harness. Open: move Docker-network mode into repo. |
| `README.md` / `CLAUDE.md` / `benchmark/pilot/README.md` | Document Docker quickstart, current Docker baseline, and remaining benchmark work. |
| `tests/docker/test_login_persistence.py` | Open: gated recreate-with-volumes invariant + dual round-trip. |

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Codex OAuth callback port / Docker Desktop localhost quirks | Use the implemented in-container `codex login` plus `socat` callback forwarding; do **not** seed/copy host ChatGPT tokens. Document `--with-api-key` as a separate fallback. |
| Claude creds not copyable from macOS Keychain | In-container `claude setup-token` (code-paste) is the primary path — host-independent. |
| Tokens expire after long idle | Entrypoint preflight detects + instructs `make docker-login`; document expected longevity. |
| arm64 image incompatibilities (mysql:5.7, EOL-buster) | `DOCKER_DEFAULT_PLATFORM=linux/amd64` default; document slower emulated targets → higher timeouts. |
| Secret leakage into image/layers or git | `.dockerignore` excludes creds/env; volumes only; never `COPY` auth dirs; README warns volumes ≈ logged-in laptop. |
| Docker-in-Docker complexity | Default to socket-mount (simpler); DinD documented as the stricter-isolation option. |
| Scans still tripping monitoring in Mode B | Make **Mode A (internal network)** the recommended default; or run on a dedicated VM. |

---

## 11. Out of scope for v1 (explicit)
Multi-stage slim image; cross-run resume of agent sessions; a registry-published image; Kubernetes/job
runner; automatic token refresh daemon; the worker-mesh/event-sourced framework upgrades (tracked
separately in the redesign roadmap).
