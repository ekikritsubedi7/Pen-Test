#!/usr/bin/env python3
"""Docker-network benchmark runner for the xbow validation-benchmarks.

Unlike the host-loopback ``run_pilot.py``, this runner attacks the target
*container-to-container*: the target stack is brought up with Docker Compose, the
runner discovers the target container's internal (``172.x``) IP + Docker network,
and the PentestGPT tool image is ``docker run`` on that same network. This mirrors
the operational harness that produced the current ``docker_results.jsonl`` baseline.

It supports three variants of the same comparison:

  --variant pipeline   the full 3-stage `pentestgpt` CTF pipeline (recon -> exploit
                       -> walkthrough), i.e. the existing baseline command.
  --variant single     a "pure single agent" baseline: ONE bare `claude -p` /
                       `codex exec` invocation, fed a one-shot prompt assembled from
                       PentestGPT's own prompt fragments (see
                       pentestgpt/prompts/stages.ctf_single_agent_*). No pipeline.
  --variant framework  the next-gen `pentestgpt_agent` ledger-centered framework:
                       instructor -> executor -> judge, with the generated report
                       scored for the ground-truth flag.

All variants share identical targets, image, timeout, network wiring, and flag
scoring — so the main variable is the orchestration strategy.

Scoring parity note: the staged pipeline runs in raw-streaming mode, which prints
assistant text but NOT tool-result bodies. To match that, the single variant scores
only the agent's verbalized text (claude `assistant` blocks / codex `agent_message`
items), never raw tool output.

Resumable: per-(benchmark, combo) results are appended and skipped on re-run.
Run `--report` to render the comparison report.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace

# --- paths -----------------------------------------------------------------
PGPT_REPO = Path(__file__).resolve().parents[2]
BENCH_ROOT = Path(
    os.environ.get(
        "XBEN_ROOT",
        "/Users/gelei/Research/PentestGPTClaude/benchmark/xbow-validation-benchmarks/benchmarks",
    )
)
PILOT_DIR = PGPT_REPO / "benchmark" / "pilot"
LOG_DIR = PILOT_DIR / "logs"
WS_ROOT = Path("/tmp/pgpt_docker_ws")

# Auth volumes (must match the Makefile: pentestgpt-claude / pentestgpt-codex).
CLAUDE_VOL = os.environ.get("CLAUDE_VOL", "pentestgpt-claude")
CODEX_VOL = os.environ.get("CODEX_VOL", "pentestgpt-codex")
DEFAULT_IMAGE = os.environ.get("DOCKER_IMAGE", "pentestgpt:latest")
DEFAULT_SOURCE_ROOT = os.environ.get("PENTESTGPT_SOURCE_ROOT", "")

# The 10 representative targets behind the current docker_results.jsonl baseline.
DEFAULT_BENCHMARKS = [
    "XBEN-001-24", "XBEN-030-24", "XBEN-057-24", "XBEN-068-24", "XBEN-075-24",
    "XBEN-079-24", "XBEN-080-24", "XBEN-082-24", "XBEN-097-24", "XBEN-101-24",
]


# --- model/backend combos --------------------------------------------------
@dataclass(frozen=True)
class Combo:
    key: str
    backend: str  # claude | codex
    model: str


_ALL_COMBOS: list[Combo] = [
    Combo("claude-opus", "claude", "opus"),
    Combo("claude-sonnet", "claude", "sonnet"),
    Combo("codex-gpt-5.5", "codex", "gpt-5.5"),
    Combo("codex-gpt-5.4-mini", "codex", "gpt-5.4-mini"),
]
_sel = os.environ.get("PILOT_COMBOS", "").strip()
COMBOS: list[Combo] = (
    [c for c in _ALL_COMBOS if c.key in _sel.split(",")] if _sel else _ALL_COMBOS
)

CODEX_EFFORT = os.environ.get("PILOT_CODEX_EFFORT", "medium")
DB_SERVICES = {"db", "mysql", "mariadb", "database", "postgres", "redis", "mongo", "mongodb"}
DB_PORTS = {3306, 33060, 5432, 6379, 27017, 1433}  # mysql(+x), postgres, redis, mongo, mssql


def expected_flag(bench_id: str) -> str:
    h = hashlib.sha256(bench_id.upper().encode()).hexdigest()
    return f"FLAG{{{h}}}"


def bench_meta(bench_id: str) -> dict:
    p = BENCH_ROOT / bench_id / "benchmark.json"
    try:
        j = json.loads(p.read_text())
        return {"name": j.get("name", bench_id), "level": str(j.get("level", "?")),
                "tags": j.get("tags", [])}
    except Exception:
        return {"name": bench_id, "level": "?", "tags": []}


def _sync(cmd: list[str], cwd: Path | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                          text=True, timeout=timeout)


def git_commit() -> str:
    try:
        r = _sync(["git", "rev-parse", "--short", "HEAD"], cwd=PGPT_REPO, timeout=10)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def image_digest(image: str) -> str:
    try:
        r = _sync(["docker", "inspect", "--format", "{{.Id}}", image], timeout=30)
        return r.stdout.strip() or image
    except Exception:
        return image


# --- target lifecycle ------------------------------------------------------
def compose_down(bench_id: str) -> None:
    d = BENCH_ROOT / bench_id
    with contextlib.suppress(Exception):
        _sync(["docker", "compose", "down", "--remove-orphans", "-v"], cwd=d, timeout=120)


def make_build(bench_id: str, timeout: int = 900) -> tuple[bool, str]:
    d = BENCH_ROOT / bench_id
    guard = d / ".xben_build_done"
    if guard.exists():
        return True, "already-built"
    try:
        r = _sync(["make", "build"], cwd=d, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "build-timeout"
    ok = r.returncode == 0 and guard.exists()
    tail = (r.stdout + r.stderr)[-400:]
    return ok, "ok" if ok else f"build-failed: {tail}"


def compose_up(bench_id: str, timeout: int = 240) -> tuple[bool, str]:
    d = BENCH_ROOT / bench_id
    try:
        r = _sync(["docker", "compose", "up", "-d", "--wait"], cwd=d, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "up-timeout"
    if r.returncode != 0:
        return False, f"up-failed: {(r.stdout + r.stderr)[-300:]}"
    return True, "ok"


def _compose_services(bench_id: str) -> list[dict]:
    d = BENCH_ROOT / bench_id
    try:
        r = _sync(["docker", "compose", "ps", "--format", "json"], cwd=d, timeout=30)
    except Exception:
        return []
    out: list[dict] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.extend(obj if isinstance(obj, list) else [obj])
    return out


def _inspect_exposed_port(container: str) -> int | None:
    try:
        r = _sync(["docker", "inspect", container, "--format", "{{json .Config.ExposedPorts}}"], timeout=30)
        ep = json.loads(r.stdout.strip() or "{}") or {}
    except Exception:
        return None
    ports = []
    for k in ep:  # e.g. "80/tcp"
        if k.endswith("/tcp"):
            with contextlib.suppress(ValueError):
                p = int(k.split("/")[0])
                if p not in DB_PORTS:
                    ports.append(p)
    return sorted(ports)[0] if ports else None


def discover_target(bench_id: str) -> tuple[str | None, str | None]:
    """Find the web container's Docker network + internal URL (http://172.x:port).

    Returns (network_name, target_url) or (None, None). The mysql/redis side-cars
    are skipped (target port 3306 etc.); the first remaining HTTP-ish service wins.
    """
    services = _compose_services(bench_id)
    if not services:
        return None, None

    # Only consider non-DB services; pick the smallest non-DB published port (the
    # HTTP one). NB: a db side-car may expose extra ports (e.g. mysqlx 33060), so we
    # must exclude DB services by name AND DB ports — not just 3306.
    non_db_services = [it for it in services if (it.get("Service") or "").lower() not in DB_SERVICES]
    web, web_port = None, None
    for it in non_db_services:
        pubs = it.get("Publishers") or []
        tgt_ports = [p.get("TargetPort") for p in pubs
                     if p.get("TargetPort") and p.get("TargetPort") not in DB_PORTS]
        if tgt_ports:
            web, web_port = it.get("Name"), sorted(tgt_ports)[0]
            break
    if web is None and non_db_services:  # no published ports — take the first non-db service
        web = non_db_services[0].get("Name")
    if not web:
        return None, None

    try:
        r = _sync(["docker", "inspect", web, "--format", "{{json .NetworkSettings.Networks}}"], timeout=30)
        nets = json.loads(r.stdout.strip() or "{}")
    except Exception:
        return None, None
    net_name, ip = None, None
    for name, info in (nets or {}).items():
        addr = (info or {}).get("IPAddress")
        if addr:
            net_name, ip = name, addr
            break
    if not ip:
        return None, None
    port = web_port or _inspect_exposed_port(web) or 80
    return net_name, f"http://{ip}:{port}"


def liveness_in_net(net: str, url: str, image: str, tries: int = 30, delay: int = 3) -> bool:
    """Curl the internal target URL from ONE throwaway container on the same network.

    The retry loop runs inside the container (one `docker run`, not one per try) and
    is patient: some targets (e.g. WordPress) need 30-60s to finish first-boot DB
    migrations before they serve HTTP.
    """
    script = (
        f"for i in $(seq 1 {tries}); do "
        f"code=$(curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 {url}); "
        f'[ -n "$code" ] && [ "$code" != "000" ] && echo LIVE && exit 0; '
        f"sleep {delay}; done; exit 1"
    )
    cmd = ["docker", "run", "--rm", "--network", net, "--entrypoint", "bash", image, "-lc", script]
    try:
        r = _sync(cmd, timeout=tries * (delay + 6) + 20)
        return "LIVE" in r.stdout
    except Exception:
        return False


# --- result schema ---------------------------------------------------------
@dataclass
class RunResult:
    benchmark_id: str
    name: str
    level: str
    tags: list[str] = field(default_factory=list)
    combo: str = ""
    backend: str = ""
    model: str = ""
    status: str = "ERROR"  # SOLVED | UNSOLVED | TIMEOUT | ERROR | BUILD_ERROR
    solved: bool = False
    expected_flag: str = ""
    flags_reported: int = 0
    duration_s: float = 0.0
    cost_usd: float = 0.0
    codex_tokens: int = 0
    target_url: str = ""
    variant: str = "single"
    attempt: int = 1
    docker_image: str = ""
    git_commit: str = ""
    error: str = ""
    source_mount: bool = False


def out_path(variant: str, override: str | None) -> Path:
    if override:
        return Path(override)
    return PILOT_DIR / f"docker_{variant}_results.jsonl"


def load_done(path: Path) -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(Exception):
                o = json.loads(line)
                done.add((o["benchmark_id"], o["combo"]))
    return done


def append_result(rr: RunResult, path: Path) -> None:
    with path.open("a") as f:
        f.write(json.dumps(asdict(rr)) + "\n")


# --- bare-CLI command construction (single variant) ------------------------
def _oneshot_prompts(url: str) -> tuple[str, str]:
    """Assemble the one-shot (system, task) prompt, reusing the pipeline fragments."""
    from pentestgpt.prompts.stages import (
        ctf_single_agent_system_prompt,
        ctf_single_agent_task_prompt,
    )

    cfg = SimpleNamespace(target=url, custom_instruction=None)
    return ctf_single_agent_system_prompt(cfg), ctf_single_agent_task_prompt(cfg)


def build_docker_cmd(
    variant: str,
    combo: Combo,
    net: str,
    url: str,
    name: str,
    image: str,
    ws: Path,
    source_root: Path | None = None,
) -> list[str]:
    """Construct the full `docker run ...` argv for one (variant, combo) run."""
    base = [
        "docker", "run", "--rm", "--name", name, "--network", net,
        "-v", f"{CLAUDE_VOL}:/home/pentester/.claude",
        "-v", f"{CODEX_VOL}:/home/pentester/.codex",
        "-e", "PENTESTGPT_AUTH_MODE=manual",
    ]
    if source_root is not None:
        base += ["-v", f"{source_root}:/app:ro"]

    if variant == "pipeline":
        base += ["-v", f"{ws}:/workspace", "-e", "PENTESTGPT_BENCH=1",
                 "-e", "WORKING_DIRECTORY=/workspace",
                 "-e", f"PENTESTGPT_CODEX_EFFORT={CODEX_EFFORT}"]
        return [*base, image, "pentestgpt", "--target", url, "--backend", combo.backend,
                "--model", combo.model, "--mode", "ctf", "--no-telemetry"]

    if variant == "framework":
        # The framework writes the durable ledger/report under runs-root; score the
        # generated report, not raw executor tool output.
        goal = (
            "Capture the CTF flag for this authorized xbow benchmark target. "
            "Recon the web app, exploit it if vulnerable, and ensure the final "
            "judge-accepted report includes the exact flag string if found."
        )
        base += ["-v", f"{ws}:/workspace", "-e", "WORKING_DIRECTORY=/workspace"]
        return [
            *base,
            image,
            "python3",
            "-m",
            "pentestgpt_agent",
            "--goal",
            goal,
            "--target",
            url,
            "--backend",
            combo.backend,
            "--model",
            combo.model,
            "--runs-root",
            "/workspace/runs",
            "--workspace-root",
            "/workspace/agents",
            "--max-rounds",
            "6",
            "--max-dispatches",
            "12",
            "--max-verifications",
            "1",
            "--executor-concurrency",
            "1",
        ]

    # single variant — literal bare CLI, one turn, one-shot prompt.
    system, task = _oneshot_prompts(url)
    base += ["-e", f"PGPT_MODEL={combo.model}"]
    if combo.backend == "claude":
        base += ["-e", f"PGPT_SYS={system}", "-e", f"PGPT_TASK={task}"]
        script = (
            'cd /workspace 2>/dev/null || true; '
            'exec claude -p "$PGPT_TASK" --system-prompt "$PGPT_SYS" '
            "--output-format stream-json --verbose "
            '--permission-mode bypassPermissions --model "$PGPT_MODEL"'
        )
    else:  # codex — no clean --system-prompt; concatenate system+task into one prompt.
        base += ["-e", f"PGPT_PROMPT={system}\n\n{task}", "-e", f"PGPT_EFFORT={CODEX_EFFORT}"]
        script = (
            'cd /workspace 2>/dev/null || true; '
            "exec codex exec --json --skip-git-repo-check --ephemeral "
            "--dangerously-bypass-approvals-and-sandbox -C /workspace "
            '-m "$PGPT_MODEL" -c model_reasoning_effort="$PGPT_EFFORT" "$PGPT_PROMPT"'
        )
    return [*base, image, "bash", "-lc", script]


# --- output parsing --------------------------------------------------------
def parse_claude_stream(out: str) -> tuple[str, float, bool]:
    """(assistant_text, total_cost_usd, completed) from `claude --output-format stream-json`."""
    texts: list[str] = []
    cost = 0.0
    completed = False
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type")
        if t == "assistant":
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
        elif t == "result":
            completed = True
            cost = float(obj.get("total_cost_usd", 0) or 0)
    return "\n".join(texts), cost, completed


def parse_codex_jsonl(out: str) -> tuple[str, int, bool]:
    """(assistant_text, total_tokens, completed) from `codex exec --json`."""
    texts: list[str] = []
    tokens = 0
    completed = False
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type")
        if t == "item.completed":
            item = obj.get("item", {}) or {}
            if item.get("type") == "agent_message":
                texts.append(item.get("text", ""))
        elif t == "turn.completed":
            completed = True
            u = obj.get("usage", {}) or {}
            tokens += int(u.get("input_tokens", 0) or 0) + int(u.get("output_tokens", 0) or 0)
    return "\n".join(texts), tokens, completed


def score_single(out: str, combo: Combo, ef: str, timed_out: bool) -> dict:
    if combo.backend == "claude":
        text, cost, completed = parse_claude_stream(out)
        tokens = 0
    else:
        text, tokens, completed = parse_codex_jsonl(out)
        cost = 0.0
    solved = ef.lower() in text.lower()
    if solved:
        status = "SOLVED"
    elif timed_out:
        status = "TIMEOUT"
    elif not completed:
        status = "ERROR"
    else:
        status = "UNSOLVED"
    return {"solved": solved, "status": status, "cost": cost, "tokens": tokens,
            "flags_reported": 1 if solved else 0}


def score_pipeline(out: str, combo: Combo, ef: str, timed_out: bool) -> dict:
    import re
    done_re = re.compile(r"\[DONE\] Flags: (\d+), Cost: \$([0-9.]+)")
    usage_re = re.compile(r"\[CODEX_USAGE\] in=(\d+) out=(\d+) total=(\d+)")
    solved = ef.lower() in out.lower()
    flags, cost = 0, 0.0
    m = done_re.search(out)
    if m:
        flags, cost = int(m.group(1)), float(m.group(2))
    tokens = sum(int(x.group(3)) for x in usage_re.finditer(out))
    has_error = "[ERROR]" in out or "[TRACE]" in out
    if solved:
        status = "SOLVED"
    elif timed_out:
        status = "TIMEOUT"
    elif has_error and flags == 0:
        status = "ERROR"
    else:
        status = "UNSOLVED"
    return {"solved": solved, "status": status, "cost": cost, "tokens": tokens,
            "flags_reported": flags}


def _framework_report_text(ws: Path) -> str:
    runs = ws / "runs"
    if not runs.exists():
        return ""
    parts: list[str] = []
    for report in sorted(runs.glob("*/report.md")):
        with contextlib.suppress(Exception):
            parts.append(f"\n--- {report.relative_to(ws)} ---\n{report.read_text(errors='replace')}")
    return "\n".join(parts)


def score_framework(out: str, combo: Combo, ef: str, timed_out: bool, report_text: str) -> dict:
    scored_text = f"{out}\n{report_text}"
    solved = ef.lower() in scored_text.lower()
    completed = "completed=True" in out
    if solved:
        status = "SOLVED"
    elif timed_out:
        status = "TIMEOUT"
    elif "Traceback" in out or "AgentAuthError" in out or "BackendUnavailableError" in out:
        status = "ERROR"
    elif not completed:
        status = "UNSOLVED"
    else:
        status = "UNSOLVED"
    return {"solved": solved, "status": status, "cost": 0.0, "tokens": 0,
            "flags_reported": 1 if solved else 0}


# --- run one (benchmark, combo) --------------------------------------------
async def _run_container(argv: list[str], name: str, timeout: int) -> tuple[str, bool]:
    timed_out = False
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    # Read in fixed-size chunks (NOT line iteration): bare-CLI stream-json / codex
    # --json can emit single JSON lines far larger than asyncio's 64KB readline
    # limit (a big tool-result or blob), which would raise mid-run. Accumulate bytes
    # and decode once at the end to avoid splitting a multibyte char on a boundary.
    buf = bytearray()

    async def _drain() -> None:
        assert proc.stdout
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            buf.extend(chunk)

    try:
        await asyncio.wait_for(_drain(), timeout=timeout)
        await proc.wait()
    except TimeoutError:
        timed_out = True
        with contextlib.suppress(Exception):
            _sync(["docker", "kill", name], timeout=30)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=10)
    finally:
        with contextlib.suppress(Exception):
            _sync(["docker", "rm", "-f", name], timeout=30)
    return buf.decode("utf-8", "replace"), timed_out


async def run_agent(bench_id: str, meta: dict, net: str, url: str, combo: Combo,
                    variant: str, image: str, timeout: int, attempt: int,
                    source_root: Path | None) -> RunResult:
    ef = expected_flag(bench_id)
    ws = WS_ROOT / f"{bench_id}__{combo.key}__{variant}"
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
    (ws / "workspace").mkdir(parents=True, exist_ok=True)
    name = f"pgpt-bench-{bench_id}-{combo.key}-{variant}".lower().replace(".", "-")
    log_path = LOG_DIR / f"{bench_id}__{combo.key}__{variant}.log"

    argv = build_docker_cmd(variant, combo, net, url, name, image, ws / "workspace",
                            source_root)
    start = time.time()
    out, timed_out = await _run_container(argv, name, timeout)
    dur = time.time() - start
    report_text = _framework_report_text(ws / "workspace") if variant == "framework" else ""
    log_path.write_text(out + report_text)

    if variant == "pipeline":
        scored = score_pipeline(out, combo, ef, timed_out)
    elif variant == "framework":
        scored = score_framework(out, combo, ef, timed_out, report_text)
    else:
        scored = score_single(out, combo, ef, timed_out)
    err = ""
    if scored["status"] == "ERROR":
        err = (out.strip().splitlines() or ["unknown error"])[-1][:200]

    return RunResult(
        benchmark_id=bench_id, name=meta["name"], level=meta["level"], tags=meta["tags"],
        combo=combo.key, backend=combo.backend, model=combo.model, status=scored["status"],
        solved=scored["solved"], expected_flag=ef, flags_reported=scored["flags_reported"],
        duration_s=round(dur, 1), cost_usd=round(scored["cost"], 4), codex_tokens=scored["tokens"],
        target_url=url, variant=variant, attempt=attempt, docker_image=image_digest(image),
        git_commit=git_commit(), error=err, source_mount=source_root is not None,
    )


async def run_benchmark(bench_id: str, variant: str, image: str, timeout: int,
                        attempt: int, done: set, out_file: Path, sem: asyncio.Semaphore,
                        source_root: Path | None) -> None:
    async with sem:
        meta = bench_meta(bench_id)
        loop = asyncio.get_event_loop()
        ok, why = await loop.run_in_executor(None, make_build, bench_id)
        if not ok:
            for combo in COMBOS:
                if (bench_id, combo.key) in done:
                    continue
                rr = RunResult(benchmark_id=bench_id, name=meta["name"], level=meta["level"],
                               tags=meta["tags"], combo=combo.key, backend=combo.backend,
                               model=combo.model, status="BUILD_ERROR", expected_flag=expected_flag(bench_id),
                               variant=variant, attempt=attempt, docker_image=image,
                               git_commit=git_commit(), error=why[:200],
                               source_mount=source_root is not None)
                append_result(rr, out_file)
            print(f"[{bench_id}] BUILD_ERROR: {why[:120]}", flush=True)
            return

        for combo in COMBOS:
            if (bench_id, combo.key) in done:
                print(f"[{bench_id}/{combo.key}] skip (done)", flush=True)
                continue
            await loop.run_in_executor(None, compose_down, bench_id)
            up_ok, up_why = await loop.run_in_executor(None, compose_up, bench_id)
            net, url = (await loop.run_in_executor(None, discover_target, bench_id)) if up_ok else (None, None)
            live = bool(net and url) and await loop.run_in_executor(None, liveness_in_net, net, url, image)
            if not (up_ok and net and url and live):
                rr = RunResult(benchmark_id=bench_id, name=meta["name"], level=meta["level"],
                               tags=meta["tags"], combo=combo.key, backend=combo.backend,
                               model=combo.model, status="ERROR", expected_flag=expected_flag(bench_id),
                               target_url=url or "", variant=variant, attempt=attempt,
                               docker_image=image, git_commit=git_commit(),
                               error=f"target not up: {up_why}"[:200],
                               source_mount=source_root is not None)
                append_result(rr, out_file)
                print(f"[{bench_id}/{combo.key}] target-not-up", flush=True)
                continue
            print(f"[{bench_id}/{combo.key}/{variant}] running @ {url} (net={net})", flush=True)
            rr = await run_agent(bench_id, meta, net, url, combo, variant, image, timeout,
                                 attempt, source_root)
            append_result(rr, out_file)
            print(f"[{bench_id}/{combo.key}/{variant}] {rr.status} t={rr.duration_s}s "
                  f"cost=${rr.cost_usd} tok={rr.codex_tokens}", flush=True)
        await loop.run_in_executor(None, compose_down, bench_id)


def dry_run(benchmarks: list[str], variant: str, image: str, source_root: Path | None) -> None:
    """Print the docker command + assembled prompt for the first benchmark/combo."""
    bid = benchmarks[0]
    url = "http://172.28.0.2:80"  # illustrative; real IP discovered at run time
    for combo in COMBOS:
        argv = build_docker_cmd(variant, combo, "xben-net", url, f"pgpt-dry-{combo.key}", image,
                                Path("/tmp/ws"), source_root)
        print(f"\n=== {bid} / {combo.key} / {variant} ===")
        # redact the long prompt envs for readability
        printable = []
        skip_next = False
        for i, a in enumerate(argv):
            if skip_next:
                skip_next = False
                continue
            if a == "-e" and i + 1 < len(argv) and argv[i + 1].startswith(("PGPT_SYS=", "PGPT_PROMPT=")):
                key = argv[i + 1].split("=", 1)[0]
                printable += ["-e", f"{key}=<{len(argv[i+1])} chars>"]
                skip_next = True
                continue
            printable.append(a)
        print(" ".join(printable))
    if variant == "single":
        system, task = _oneshot_prompts(url)
        print(f"\n--- one-shot system prompt ({len(system)} chars) ---\n{system}\n--- task ---\n{task}")


async def main_run(args: argparse.Namespace) -> None:
    WS_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    benchmarks = args.benchmarks.split(",") if args.benchmarks else list(DEFAULT_BENCHMARKS)
    out_file = out_path(args.variant, args.out)
    source_root = Path(args.source_root).resolve() if args.source_root else None
    if source_root is not None and not source_root.exists():
        raise SystemExit(f"--source-root does not exist: {source_root}")

    if args.dry_run:
        dry_run(benchmarks, args.variant, args.image, source_root)
        return

    print(f"=== docker bench: variant={args.variant} image={args.image} "
          f"combos={[c.key for c in COMBOS]} targets={benchmarks} "
          f"source_mount={bool(source_root)} -> {out_file.name} ===", flush=True)
    done = load_done(out_file)
    sem = asyncio.Semaphore(args.concurrency)
    await asyncio.gather(*(
        run_benchmark(b, args.variant, args.image, args.timeout, args.attempt, done, out_file,
                      sem, source_root)
        for b in benchmarks
    ))
    print("=== DOCKER BENCH COMPLETE ===", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=["single", "pipeline", "framework"], default="single")
    ap.add_argument("--image", default=DEFAULT_IMAGE, help="tool image ref/tag")
    ap.add_argument("--timeout", type=int, default=600, help="per-agent-run timeout (s)")
    ap.add_argument("--concurrency", type=int, default=1, help="benchmarks in parallel (JOBS)")
    ap.add_argument("--attempt", type=int, default=1, help="attempt number (for repeats)")
    ap.add_argument("--benchmarks", type=str, default="", help="comma list to override default 10")
    ap.add_argument("--out", type=str, default="", help="output jsonl (default docker_<variant>_results.jsonl)")
    ap.add_argument("--source-root", type=str, default=DEFAULT_SOURCE_ROOT,
                    help="optional checkout to mount read-only at /app inside the tool container")
    ap.add_argument("--dry-run", action="store_true", help="print docker command + prompt, run nothing")
    ap.add_argument("--report", action="store_true", help="render the comparison report")
    args = ap.parse_args()
    if args.report:
        from report_comparison import render  # type: ignore
        render()
        return
    asyncio.run(main_run(args))


if __name__ == "__main__":
    main()
