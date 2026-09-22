# PentestGPT starting and operating SOP

Status: 2026-09-20

Internal handbook for **developers and operators**. Audience: anyone who clones this repo, verifies
it, authenticates a provider, and runs an authorized assessment.

The public root `README.md` is a separate product page and can lag this file. Do not treat README
Quick Start strings as authoritative when they conflict with this document.

Canonical design: [`architecture.md`](architecture.md). Domain language:
[`../pentestgpt_agent/CONTEXT.md`](../pentestgpt_agent/CONTEXT.md). Docker image status:
[`docker-dev-plan.md`](docker-dev-plan.md). Framework contract:
[`../pentestgpt_agent/README.md`](../pentestgpt_agent/README.md).

Use only against **explicitly authorized** targets. Both agent roles run with
`SandboxPolicy.FULL_ACCESS`. The container, VM, or attack box is the blast radius.

## Surfaces

| Surface | Command | Provider |
|---|---|---|
| Maintained autonomous loop | `pentestgpt-agent` from `pentestgpt_agent/` | Claude Code or Codex CLI |
| Human-driven USEN-2024 client | `pentestgpt-legacy` | Provider SDKs (`ANTHROPIC_API_KEY`, etc.) |
| Tool image (nmap, gobuster, CLIs) | `make docker-shell` | Persisted Claude + Codex volumes |
| Framework inside Docker | **not wired** — `make docker-run` exits 2 | — |

Do not use the root `unified_agent/` copy. The nested project imports the pinned external
`unified-agent==0.3.0` package from git (`PentestGPT-Project/UnifedAgentWrapper`, rev in
`pentestgpt_agent/pyproject.toml`). First `uv sync` needs network access to that repo. The sibling
`xbow-benchmark` checkout is reference-only.

---

## Command catalog

Every row matches the Makefile and package scripts at HEAD. Do not invent flags that `make run`
does not pass.

### Root Make

| Target | Purpose |
|---|---|
| `make help` | List Make targets |
| `make install` | Root + nested agent sync (`AGENT_EXTRA`, default `all`) |
| `make test` | Nested agent tests + root non-Docker tests |
| `make test-all` | Also run Docker contract tests |
| `make test-cov` | Root tests with coverage on `unified_agent` |
| `make test-verbose` | Root tests `-vvs` |
| `make test-fast` | Root tests excluding `slow` |
| `make test-backend` | Root Claude/Codex backend tests |
| `make test-agent` | Nested `pytest -q` |
| `make check-agent` | Nested ruff + format-check + mypy + pytest |
| `make test-agent-new` / `make check-agent-new` | Aliases for the two targets above |
| `make lint` | Ruff on root packages |
| `make lint-fix` | Ruff autofix on root packages |
| `make format` | Ruff format root packages |
| `make format-check` | Ruff format check root packages |
| `make typecheck` | Nested mypy |
| `make check` | Root lint + format-check + `check-agent` |
| `make ci` | `check` + root tests (ignore docker) + both `uv build` |
| `make ci-quick` | `check` + root tests (ignore docker); skip builds |
| `make build` | Root `uv build` |
| `make clean` | Remove build/cache artifacts |
| `make watch` | `ptw` on root tests |
| `make run` | Local agent; **requires** `TARGET=`; optional `BACKEND` (default `claude`), `MODEL`, `GOAL`. Does **not** pass `--effort`, `--run-id`, or `--resume` |
| `make docker-build` | Build `pentestgpt:latest` |
| `make docker-login` | Persist Claude + Codex login into named volumes |
| `make docker-auth-status` | Check CLI login; `ROUNDTRIP=1` spends a tiny live call |
| `make docker-shell` | Interactive tool container with auth volumes |
| `make docker-run` | Explicit failure: framework not in the image (exit 2) |
| `make docker-down` | Compose down; **keeps** auth volumes |
| `make docker-nuke` | Remove auth volumes; forces re-login |

### Maintained agent (`pentestgpt_agent/`)

Work from this directory so the root compatibility copy cannot shadow imports.

```bash
uv sync --extra claude       # or: codex / all
uv run python -m pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv lock --check
uv build
```

Live smoke (spends tokens):

```bash
PENTESTGPT_AGENT_LIVE=1 \
PENTESTGPT_AGENT_BACKEND=claude \
PENTESTGPT_AGENT_MODEL=claude-opus-4-8 \
uv run python -m pytest tests/live/test_local_model.py -q -s
```

`uv run pentestgpt-agent`:

| Flag | Notes |
|---|---|
| `--goal` | Required |
| `--target` | Required; repeatable; every value must be in scope |
| `--backend` | `claude` (default) or `codex` |
| `--model` | Optional; omit for wrapper default |
| `--effort` | Claude: `low`, `medium`, `high`, `xhigh`, `max` |
| `--run-id` | Directory name under `--runs-root` (default auto) |
| `--runs-root` | Default `runs/` |
| `--workspace-root` | Default `agent-workspaces/` |
| `--max-decisions` | Default 20 Supervisor cycles |
| `--supervisor-max-turns` / `--executor-max-turns` | Default 4 / 12 |
| `--resume` | Exact `trial-config.json` match required, including hashes and `unified-agent` version |

`uv run pentestgpt-agent-audit`:

| Flag | Notes |
|---|---|
| `--run-dir` | Required path to a completed or in-progress run |
| `--expected-flag` | Required held-out oracle (do not commit real flags) |
| `--output` | Optional JSON path |

### Legacy (`pentestgpt-legacy`)

Installed from the root package:

| Command / flag | Notes |
|---|---|
| `pentestgpt-legacy` | Interactive USEN-2024 session |
| `--reasoning-model` / `--parsing-model` / `--generation-model` | Per-session models |
| `--base-url` | OpenAI-compatible override (e.g. Ollama) |
| `--log-dir` | Default `logs` |
| `--list-models` | Registry dump |
| `--smoke-test` | Live round-trip every configured model |
| `--provider` / `--model` | Restrict smoke-test |
| `--version` | Package version |
| `pentestgpt-legacy-connection` | Flagship-per-provider connectivity probe |

### Do not run (stale but still in the tree)

| String | Why |
|---|---|
| Public README `pentestgpt --target` / `--mode` / `--list-sessions` / `--no-telemetry` | No such CLI in current packaging |
| `make docker-run TARGET=...` | Image does not contain `pentestgpt_agent`; exits 2 |
| `make connect` | Printed by `scripts/config.sh`; target does not exist |
| `./setup.sh` then run `pentestgpt-agent` in Docker | Script builds the tool image; framework binary is not in it |

---

## Starting

### Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/), Git
- For Claude runs: Claude Code CLI installed and authenticated
- For Codex runs: Codex CLI installed and authenticated
- For the tool image: Docker

### First install

```bash
git clone <this-repo>
cd PentestGPT
make install                 # root + pentestgpt_agent, AGENT_EXTRA=all
# or narrower:
cd pentestgpt_agent && uv sync --extra claude
cd pentestgpt_agent && uv sync --extra all
```

`make install` / nested `uv sync` pull `unified-agent` from the pinned UnifedAgentWrapper git rev,
not from the obsolete root `unified_agent/` tree.

### Pick a first-time path

```text
clone + make install
  -> developer gate:          make check
  -> autonomous local:        Claude/Codex CLI auth -> cd pentestgpt_agent && uv run pentestgpt-agent ...
  -> legacy interactive:      provider API keys -> pentestgpt-legacy
  -> tool image only:         make docker-build / docker-login / docker-shell
                              (tools + CLIs; not the framework)
```

Developer verification (no live target):

```bash
make check          # root lint/format + nested gate
make ci             # full local CI simulation
```

From `pentestgpt_agent/` alone: pytest, ruff, mypy, `uv lock --check` as listed in the catalog.

### Connect Claude Code (local)

Official docs: [Claude Code setup](https://code.claude.com/docs/en/setup),
[authentication](https://code.claude.com/docs/en/authentication). Native installer auto-updates;
npm install needs Node.js 22+ and should not use `sudo`.

```bash
# Preferred on Linux / macOS / WSL
curl -fsSL https://claude.ai/install.sh | bash

# Alternative
npm install -g @anthropic-ai/claude-code
```

#### Subscription login (interactive)

```bash
cd /path/to/PentestGPT
claude
```

First launch opens a browser. If it does not, press `c` to copy the URL. If the browser shows a
code instead of redirecting (WSL2, SSH, containers), paste it at `Paste code here if prompted`.
Success prints `Login successful`.

`ANTHROPIC_API_KEY` in the environment **overrides** subscription OAuth. To force the Pro/Max
login:

```bash
unset ANTHROPIC_API_KEY
claude
```

#### Headless / CI token

`claude setup-token` prints a long-lived OAuth token (about one year). It requires a Claude
subscription. It is for model requests, not Remote Control or claude.ai connectors.

```bash
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat01-...'   # do not commit, do not echo
```

#### API key (pay-per-token)

```bash
export ANTHROPIC_API_KEY='sk-ant-...'   # console.anthropic.com/settings/keys
```

This is the native path for `pentestgpt-legacy`. The autonomous loop still needs the `claude` binary
on `PATH`; the key only authenticates that CLI.

#### Verify the CLI

```bash
command -v claude
claude -p "reply with exactly OK" --model sonnet
```

A one-line `OK` means auth works. That call spends a small amount of quota.

#### Use Claude Code on this repo (developer)

`CLAUDE.md` at the repo root is the in-repo instruction file. Launch from the repository root so it
is picked up. Do not paste provider credentials, VPN files, HTB tokens, flags, or raw traces into
the chat.

### Connect Claude Code (Docker tool image)

The image already contains the `claude` binary. Login state lives in named volumes, never in image
layers:

```text
pentestgpt-claude -> /home/pentester/.claude
pentestgpt-codex  -> /home/pentester/.codex
```

Host Keychain credentials cannot be copied into Linux containers. The supported Claude path is
`setup-token`, stored as `/home/pentester/.claude/oauth_token`. `scripts/entrypoint.sh` exports it
as `CLAUDE_CODE_OAUTH_TOKEN` on every start.

```bash
make docker-build
make docker-login            # live-checks both CLIs; logs in only what is missing
make docker-auth-status
ROUNDTRIP=1 make docker-auth-status   # spends a tiny Claude + Codex call
make docker-shell            # interactive tool container, auth volumes attached
```

`make docker-login` for Claude:

1. Runs `claude setup-token` in the container.
2. Approve in the browser.
3. Copy the printed token (`sk-ant-oat01-...`).
4. Paste at the hidden host prompt. The script writes it into the volume via stdin (never argv/env).

Codex is a **separate** in-container `codex login`. ChatGPT refresh tokens are single-use; do not
copy host `auth.json`. The OAuth callback is forwarded with `socat` on host port 1455.

| Command | Auth volumes |
|---|---|
| `make docker-down` | kept |
| `make docker-nuke` | **deleted** — forces a full re-login |

Treat those volumes like a logged-in workstation.

#### Auth modes inside the image

`PENTESTGPT_AUTH_MODE` (compose / `.env.auth`):

| Mode | When | What happens |
|---|---|---|
| `manual` (default) | Claude subscription via `make docker-login` | Exports `CLAUDE_CODE_OAUTH_TOKEN` from the volume |
| `anthropic` | `ANTHROPIC_API_KEY` | Direct Anthropic key; no setup-token |
| `openrouter` / `local` | CCR on port 3456 | Routes `claude` through Claude Code Router |

CCR is an image-side router for OpenRouter or a host LLM. It is not required for the maintained
`pentestgpt-agent` loop.

---

## Operating

### Run the maintained agent (local)

Prefer the direct CLI when you need effort, run-id, resume, or multiple `--target` values.
`make run` is a thin wrapper: `TARGET` required; `BACKEND` default `claude`; optional `MODEL` and
`GOAL` only.

```bash
# Makefile wrapper
make run TARGET=http://127.0.0.1:8000 BACKEND=claude

make run TARGET=http://127.0.0.1:8000 BACKEND=claude \
  MODEL=claude-opus-4-8 GOAL='Capture the flag from this authorized target.'
```

```bash
cd pentestgpt_agent

uv run pentestgpt-agent \
  --goal "Capture the flag from this authorized target." \
  --target http://127.0.0.1:8080 \
  --backend claude \
  --model claude-opus-4-8 \
  --effort xhigh \
  --run-id example
```

Claude episodes set `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`. Provider conversation history is not
memory. SQLite + trace receipts are.

### Resume

`--resume` requires an exact `trial-config.json` match (goal, targets, provider, model, effort,
prompt/schema hashes, budgets, both full-access policies, environment, `unified-agent` version).

```bash
uv run pentestgpt-agent \
  --goal "Capture the flag from this authorized target." \
  --target http://127.0.0.1:8080 \
  --backend claude \
  --model claude-opus-4-8 \
  --effort xhigh \
  --run-id example \
  --resume
```

`make run` cannot resume; use the direct CLI.

### Audit (CTF proof)

`COMPLETED` means structural evidence citation, not arbitrary natural-language entailment. CTF
proof is a held-out oracle audit. Do not put real flags in git.

```bash
uv run pentestgpt-agent-audit \
  --run-dir runs/example \
  --expected-flag 'FLAG{...}' \
  --output runs/example-audit.json
```

### Legacy interactive

```bash
pentestgpt-legacy
pentestgpt-legacy --list-models
pentestgpt-legacy --smoke-test
pentestgpt-legacy-connection
```

### Live process inspector (developer diagnostic)

Not a start path. The pinned `unified-agent` 0.3 dependency can expose a read-only local web
inspector for live provider episodes. See [`../pentestgpt_agent/README.md`](../pentestgpt_agent/README.md)
(Live process inspector). Prefer the framework's own trace journal as the canonical record.

### Isolation

- Authorize the target in writing. Do not point this at random internet hosts.
- Do not mount home directories, extra tokens, host Docker sockets, or unrelated source.
- Mount run state only when you need persistence. Traces and SQLite contain target output.
- Tear the environment down after the assessment.
- The image user `pentester` has passwordless sudo. Isolation from the host exists only when
  mounts, caps, devices, and networking are constrained on purpose.
- `docker-compose.yml` adds `NET_ADMIN` and `/dev/net/tun` for optional VPN. Do not enable that on
  a shared workstation unless the engagement requires it.
- Never commit `.env`, `.env.auth`, `oauth_token`, `auth.json`, VPN configs, HTB tokens, flags, or
  raw traces.

### Failure / restart (operator view)

- Operational failures retry only when no external-action receipt exists.
- Actionful failures are never auto-replayed.
- Existing terminal traces are compiled before any provider reinvocation.
- `--resume` fails closed on any trial-config mismatch.
- `COMPLETED` means structural evidence citation. CTF proof is the held-out audit, not the model’s
  prose.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `claude` missing on host | CLI not installed | Native `install.sh` or npm; then re-open the shell |
| Login prompt despite subscription | `ANTHROPIC_API_KEY` set | `unset ANTHROPIC_API_KEY` |
| Browser code, no redirect | Container / WSL / SSH callback | Paste the code into the CLI |
| Docker Claude not logged in | Volume empty or stale token | `make docker-login`; confirm `ROUNDTRIP=1 make docker-auth-status` |
| `make docker-run` exits 2 | Framework is not in the image | `make run TARGET=...` on the host |
| `make connect` not found | Dead `config.sh` string | Ignore it; use `docker-login` / `docker-shell` / `make run` |
| Importing the wrong `unified_agent` | Running from the repo root env | `cd pentestgpt_agent && uv run ...` |
| Resume rejected | Goal/target/model/effort/hashes/version differ | New `--run-id`, or match `trial-config.json` exactly |
| Claude auto-memory / extra traffic | Host env leaking into the process | Framework already disables these for Claude trials |
| `uv sync` cannot fetch unified-agent | No network or bad git rev | Check access to UnifedAgentWrapper; confirm `tool.uv.sources` rev |

### Do not

- Bake credentials into the image.
- Copy Codex `auth.json` from the host.
- Restore XBOW runners or result archives into this repo.
- Add a third always-on LLM role, RAG layer, or scheduler without trace evidence that the
  deterministic seam cannot handle the problem.
- Put flags, tokens, or full traces in issues, PRs, or chat.
- Follow stale public README / `setup.sh` / `make connect` strings over this SOP.
