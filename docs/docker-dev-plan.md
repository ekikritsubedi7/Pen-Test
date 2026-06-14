# Development plan — run the whole PentestGPT pipeline in Docker

**Goal.** One reproducible Docker image that contains the full PentestGPT solution; a user
**installs once**, does a **one-time interactive login for both Claude Code and Codex**, and from then
on can repeatedly: spawn a container → run the pipeline against an xbow target (any model / pipeline /
mode) → collect results — **without ever logging in again**.

This plan follows the *existing* build patterns (the `Dockerfile` + `docker-compose.yml` +
`scripts/entrypoint.sh` + Makefile already in the repo) and extends them; it does not start from scratch.

---

## Implementation status (2026-06-14)

**Phases 1–3 are built and verified.** The benchmark is intentionally NOT in the image — the image is
the tool only; the benchmark drives it from outside, later.

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
- ⬜ **Phases 4–6** (isolated-network mode for real targets, benchmark wiring from outside, CI test) remain.

---

## 1. Where things stand today (verified)

| Piece | State | Gap for this goal |
|---|---|---|
| `Dockerfile` | Ubuntu 24.04 + py3.12 + pentest tools (nmap, ripgrep, …) + Node 20 + **Claude CLI** (native installer) + `uv` + CCR; installs `pentestgpt/` (the fixed pipeline only). Non-root `pentester`. | No **Codex** CLI / `openai_codex` SDK; doesn't install `unified_agent/` or `pentestgpt_agent/`; no benchmark harness; no `gobuster`/`sqlmap`/`nikto`/`ffuf`. |
| `docker-compose.yml` | Persists `~/.claude` via **named volume `claude-config`**; CCR volume; host-gateway; `NET_ADMIN`. | No **`codex-config`** volume; no results/fixtures mounts; no login service; arch (`linux/amd64`) not pinned. |
| `scripts/entrypoint.sh` | Auth-mode dispatch: `openrouter`/`local` (CCR), `anthropic` (API key), `manual` (`claude login`). | No Codex auth handling; no "are both CLIs logged in?" preflight. |
| Makefile | `build` = `uv build` (python), `run` = local. | **No docker targets at all** (`docker-build`, `docker-login`, `docker-run`, `docker-bench`). |
| Auth — **Claude** | macOS host → **Keychain** (not a portable file). Linux container → `~/.claude/.credentials.json` (file). `claude setup-token` issues a long-lived token via **code-paste** (no localhost callback). | First login must happen **inside** the container (mac creds can't be copied); then persisted by `claude-config`. |
| Auth — **Codex** | **File-based, portable**: `~/.codex/auth.json` (`auth_mode`, `tokens`, `last_refresh`) + `~/.codex/config.toml`. `codex login` = ChatGPT OAuth (browser + localhost callback); `codex login --with-api-key` = API key via stdin. | Add a `codex-config` volume; seed from host **or** login in-container (callback port). |
| Backend wiring | `pentestgpt --backend {claude,codex}` already implemented (`pentestgpt/core/backend.py`). | — |
| Benchmark harness | `benchmark/pilot/run_pilot.py` runs on host today, builds/ups xbow stacks, publishes to loopback. | Make it run *inside* the container and reach the target over Docker networking. |

**Design driver:** the only genuinely hard problem is **persisting two independent login sessions**.
Everything else is packaging. The two auth systems behave differently, so they get different (but
symmetric) handling, both ending in a **named volume** so login survives container recreation.

---

## 2. Success criteria (Definition of Done)

1. `make docker-build` produces an image with the full solution + both CLIs + the pentest toolchain.
2. `make docker-login` — a **one-time** interactive step — leaves **both** Claude and Codex
   authenticated in persistent volumes. Re-running any container afterward needs **no login**.
3. `make docker-run TARGET=… BACKEND=… MODEL=… MODE=…` runs the pipeline against an xbow target and
   writes results to a host-visible directory.
4. `make docker-bench` runs the multi-model benchmark harness end-to-end inside Docker and produces
   `REPORT.md`.
5. A **login-persistence test** proves that after `down`/recreate (volumes kept), both CLIs are still
   logged in (verified by `claude` and `codex login status` non-interactively, and one real 1-token
   round-trip each).
6. Works for **multiple pipelines/settings**: CTF & pentest modes; Claude (`opus`/`sonnet`) & Codex
   (`gpt-5.5`/`gpt-5.4-mini`); and a smoke of the next-gen `pentestgpt_agent` framework.

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

## 4. Image design (extend the existing Dockerfile)

Add to the current image (keep the structure; layer additions so caching stays good):
1. **Codex CLI** — install the `codex` binary (npm `@openai/codex` or the official installer) for the
   `pentester` user; ensure it's on `PATH`.
2. **Python deps** — install the project with the **codex extra** so `openai_codex` (the SDK the
   `CodexBackend` imports) is present: `uv pip install --system /app` over a `pyproject` that includes
   `unified_agent`/`pentestgpt_agent` deps. Copy `unified_agent/`, `pentestgpt_agent/`, and
   `benchmark/` into the image (today only `pentestgpt/` is copied).
3. **Pentest toolchain** the agents actually call — add `gobuster`, `ffuf`, `nikto`, `sqlmap`,
   `seclists`/wordlists, plus the existing `nmap`. (These showed up in the live logs.)
4. **Docker CLI** (client only) — so the in-container benchmark harness can drive `docker compose` for
   the xbow target stacks (talks to a mounted host socket; see §5).
5. Pin **`DOCKER_DEFAULT_PLATFORM=linux/amd64`** as an env default for target builds (fixes
   `mysql:5.7` / EOL-buster on arm64).
6. Keep the non-root `pentester` user, the entrypoint, and CCR (unchanged) for backward compat.

> Multi-stage optional later for size; not required for v1.

---

## 5. Targets, networking & results

The agent must reach the xbow target but **not** trip host endpoint monitoring (the reason a prior host
run was halted). Two supported modes, selectable by a compose profile:

- **Mode A — co-located isolated network (recommended).** The harness brings up each xbow stack with
  **no host-published ports** on an **`--internal` Docker bridge**, and the agent container joins that
  bridge (reaching the target by service name) plus a second NAT NIC for model-API egress only. Scan
  traffic stays on the bridge — never on host loopback. (This is the design from
  `benchmark/pilot/README.md` → "run the whole sweep in Docker".)
- **Mode B — simple loopback (today's behavior).** Targets publish to loopback and the agent uses
  `host.docker.internal`. Easier, but scans cross host endpoints — only for already-isolated hosts/VMs.

**Docker-driving-Docker:** mount `/var/run/docker.sock` into the agent container so the harness can
`make build` / `docker compose up` the target stacks (simplest), **or** run true DinD for full nesting.
**Results & fixtures:** bind-mount `./benchmark/pilot/{results.jsonl,logs,REPORT.md}` and the xbow
fixtures path out of the container so results persist and runs stay resumable.

---

## 6. UX — Make targets (mirror existing patterns)

```
make docker-build         # docker compose build (image with both CLIs + full solution)
make docker-login         # ONE-TIME: interactive claude setup-token + codex login/seed -> volumes
make docker-auth-status   # non-interactive check both CLIs are authed (used by CI + preflight)
make docker-shell         # interactive shell in the container (volumes attached)
make docker-run TARGET=http://… BACKEND=claude MODEL=opus MODE=ctf
make docker-bench BENCHES=XBEN-001-24,… COMBOS=… TIMEOUT=540   # the multi-model harness
make docker-down          # stop (KEEP volumes — stays logged in)
make docker-nuke          # stop + remove volumes (forces re-login) — explicit, separate target
```

Entrypoint gains a **preflight**: if `PENTESTGPT_AUTH_MODE=manual` and either CLI is unauthenticated,
print "run `make docker-login`" and exit non-zero (fail fast, not mid-run).

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
- **Phase 4 — Isolated networking (Mode A).** Internal bridge + co-located agent + no host ports.
  ✔ target reachable from agent; **no** benchmark traffic on host loopback (verify with a host-side
  capture); ✔ `DOCKER_DEFAULT_PLATFORM=linux/amd64` makes a `mysql:5.7` challenge boot.
- **Phase 5 — Benchmark + matrix.** Wire `make docker-bench` and `make docker-test-matrix`. ✔ a small
  sweep across all four combos + a framework smoke all run in-container; `REPORT.md` generated.
- **Phase 6 — Docs/CI.** Update README + CLAUDE.md (docker quickstart), add a `tests/docker/` marker
  test for the login-persistence invariant (gated, opt-in like the live smoke).

Each phase is independently verifiable; Phase 2 is the linchpin and is gated by the persistence test.

---

## 9. File-by-file change list

| File | Change |
|---|---|
| `Dockerfile` | Add codex CLI, `openai_codex`, copy `unified_agent/ pentestgpt_agent/ benchmark/`, add scanners + docker CLI, `DOCKER_DEFAULT_PLATFORM` env, ensure codex on PATH. |
| `docker-compose.yml` | Add `codex-config` volume; results/fixtures bind-mounts; `login` + `bench` compose profiles; optional internal network; docker-socket mount for the harness. |
| `scripts/entrypoint.sh` | Add Codex preflight + a unified "both-authed?" check; keep CCR/anthropic/manual modes. |
| `scripts/docker-login.sh` (new) | Orchestrate claude `setup-token` + codex seed/login with clear prompts + final verification. |
| `scripts/docker-auth-status.sh` (new) | Non-interactive dual-auth check (exit codes for CI/preflight). |
| `Makefile` | New `docker-build/login/auth-status/shell/run/bench/test-matrix/down/nuke` targets. |
| `.dockerignore` (new) | Exclude `.env*`, `~/.claude`, `~/.codex`, `workspace/`, `runs/`, `benchmark/**/logs`, caches. |
| `benchmark/pilot/run_pilot.py` | Add an in-container mode: discover target via Docker DNS / `host.docker.internal`; honor `DOCKER_DEFAULT_PLATFORM`; configurable fixtures path. |
| `README.md` / `CLAUDE.md` | Docker quickstart: install once → `make docker-login` → `make docker-run`/`docker-bench`. |
| `tests/docker/test_login_persistence.py` (new, gated) | Recreate-with-volumes invariant + dual round-trip. |

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Codex OAuth callback port unknown / Docker-Desktop localhost quirks | Prefer **seed-from-host** for codex (portable file); for in-container login publish the confirmed callback port or use `--network host` on Linux; document `--with-api-key` fallback. |
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
