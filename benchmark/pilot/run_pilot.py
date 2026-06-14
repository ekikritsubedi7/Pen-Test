#!/usr/bin/env python3
"""Host-based multi-backend pilot runner for the xbow validation-benchmarks.

For each selected medium/hard challenge it:
  1. `make build`s the target (bakes FLAG{sha256(UPPER dir)} as ground truth),
  2. brings up a fresh container per model run and discovers its localhost port,
  3. runs the pentestgpt CTF pipeline on the host across N (backend, model) combos,
  4. judges success by whether the ground-truth flag appears in captured stdout,
  5. tears the container down.

Build failures (e.g. EOL Debian buster images) are tolerated: a larger candidate
pool is supplied and the first PILOT_SIZE that build + serve are used.

Resumable: per-(benchmark, combo) results are appended to results.jsonl and
skipped on re-run. Run `--report` to (re)render the markdown table from results.

This script is intentionally standalone (no import of the pentestgpt package) so it
can drive the CLI exactly as a user would.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

# --- paths -----------------------------------------------------------------
PGPT_REPO = Path("/Users/gelei/Research/PentestGPT")
BENCH_ROOT = Path(
    "/Users/gelei/Research/PentestGPTClaude/benchmark/xbow-validation-benchmarks/benchmarks"
)
PILOT_DIR = PGPT_REPO / "benchmark" / "pilot"
LOG_DIR = PILOT_DIR / "logs"
RESULTS_JSONL = PILOT_DIR / "results.jsonl"
WS_ROOT = Path("/tmp/pgpt_pilot_ws")


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
# Optional subset for smoke-tests: PILOT_COMBOS="claude-sonnet,codex-gpt-5.4-mini"
_sel = os.environ.get("PILOT_COMBOS", "").strip()
COMBOS: list[Combo] = (
    [c for c in _ALL_COMBOS if c.key in _sel.split(",")] if _sel else _ALL_COMBOS
)

# Candidate pool (medium=L2 / hard=L3), category-diverse, biased away from the
# phantomjs/buster XSS images that no longer build. First PILOT_SIZE that build
# and serve are used.
CANDIDATES: list[str] = [
    # L2 medium
    "XBEN-001-24",  # idor, default_credentials (mysql)
    "XBEN-078-24",  # sqli
    "XBEN-079-24",  # lfi
    "XBEN-030-24",  # cve, command_injection
    "XBEN-068-24",  # command_injection
    "XBEN-082-24",  # command_injection
    "XBEN-040-24",  # blind_sqli
    "XBEN-080-24",  # ssti
    "XBEN-086-24",  # ssti
    "XBEN-091-24",  # jwt, privilege_escalation
    "XBEN-097-24",  # path_traversal
    "XBEN-100-24",  # nosqli, graphql
    "XBEN-075-24",  # insecure_deserialization
    "XBEN-081-24",  # insecure_deserialization
    "XBEN-055-24",  # privilege_escalation, business_logic
    "XBEN-022-24",  # ssti, default_credentials, path_traversal
    "XBEN-094-24",  # command_injection
    "XBEN-103-24",  # information_disclosure, idor, crypto, privesc
    # L3 hard
    "XBEN-057-24",  # insecure_deserialization
    "XBEN-093-24",  # ssti
    "XBEN-101-24",  # crypto
    "XBEN-018-24",  # xss (may fail build)
]

PILOT_SIZE = 12


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


def compose_down(bench_id: str) -> None:
    d = BENCH_ROOT / bench_id
    with contextlib.suppress(Exception):
        _sync(["docker", "compose", "down", "--remove-orphans", "-v"], cwd=d, timeout=120)


def make_build(bench_id: str, timeout: int = 900) -> tuple[bool, str]:
    d = BENCH_ROOT / bench_id
    # Remove the make build guard so a rebuild actually re-runs.
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


def discover_url(bench_id: str) -> str | None:
    d = BENCH_ROOT / bench_id
    try:
        r = _sync(["docker", "compose", "ps", "--format", "json"], cwd=d, timeout=30)
    except Exception:
        return None
    port = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        items = obj if isinstance(obj, list) else [obj]
        for it in items:
            for p in (it.get("Publishers") or []):
                pub = p.get("PublishedPort")
                tgt = p.get("TargetPort")
                if pub and tgt != 3306:  # skip the mysql side-car
                    port = pub
    if port:
        return f"http://127.0.0.1:{port}"
    return None


def liveness(url: str, tries: int = 10) -> bool:
    for _ in range(tries):
        try:
            r = _sync(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url], timeout=10)
            if r.stdout.strip() and r.stdout.strip() != "000":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


# --- result schema ---------------------------------------------------------
@dataclass
class RunResult:
    benchmark_id: str
    name: str
    level: str
    tags: list[str]
    combo: str
    backend: str
    model: str
    status: str  # SOLVED | UNSOLVED | TIMEOUT | ERROR | BUILD_ERROR
    solved: bool
    expected_flag: str
    flags_reported: int
    duration_s: float
    cost_usd: float
    codex_tokens: int
    target_url: str
    error: str = ""


def load_done() -> set[tuple[str, str]]:
    done = set()
    if RESULTS_JSONL.exists():
        for line in RESULTS_JSONL.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
                done.add((o["benchmark_id"], o["combo"]))
            except Exception:
                continue
    return done


def append_result(rr: RunResult) -> None:
    with RESULTS_JSONL.open("a") as f:
        f.write(json.dumps(asdict(rr)) + "\n")


DONE_RE = re.compile(r"\[DONE\] Flags: (\d+), Cost: \$([0-9.]+)")
USAGE_RE = re.compile(r"\[CODEX_USAGE\] in=(\d+) out=(\d+) total=(\d+)")


async def run_agent(bench_id: str, meta: dict, url: str, combo: Combo, timeout: int) -> RunResult:
    ef = expected_flag(bench_id)
    ws = WS_ROOT / f"{bench_id}__{combo.key}"
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{bench_id}__{combo.key}.log"

    env = dict(os.environ)
    env["PENTESTGPT_BENCH"] = "1"
    env["PENTESTGPT_CODEX_EFFORT"] = os.environ.get("PILOT_CODEX_EFFORT", "medium")
    env["WORKING_DIRECTORY"] = str(ws / "workspace")

    cmd = [
        "uv", "run", "pentestgpt",
        "--target", url,
        "--backend", combo.backend,
        "--model", combo.model,
        "--mode", "ctf",
        "--no-telemetry",
    ]
    start = time.time()
    timed_out = False
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(PGPT_REPO), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, env=env, start_new_session=True,
    )
    captured: list[str] = []
    try:
        async def _drain() -> None:
            assert proc.stdout
            async for raw in proc.stdout:
                captured.append(raw.decode("utf-8", "replace"))
        await asyncio.wait_for(_drain(), timeout=timeout)
        await proc.wait()
    except TimeoutError:
        timed_out = True
        try:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            await asyncio.wait_for(proc.wait(), timeout=8)
        except Exception:
            with contextlib.suppress(Exception):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    dur = time.time() - start
    out = "".join(captured)
    log_path.write_text(out)

    solved = ef.lower() in out.lower()
    flags = 0
    cost = 0.0
    m = DONE_RE.search(out)
    if m:
        flags = int(m.group(1))
        cost = float(m.group(2))
    tokens = sum(int(x.group(3)) for x in USAGE_RE.finditer(out))
    has_error = "[ERROR]" in out or "[TRACE]" in out

    if solved:
        status = "SOLVED"
    elif timed_out:
        status = "TIMEOUT"
    elif has_error and flags == 0:
        status = "ERROR"
    else:
        status = "UNSOLVED"

    err = ""
    if status == "ERROR":
        em = re.search(r"\[ERROR\] (.+)", out)
        err = em.group(1)[:200] if em else "unknown error"

    return RunResult(
        benchmark_id=bench_id, name=meta["name"], level=meta["level"], tags=meta["tags"],
        combo=combo.key, backend=combo.backend, model=combo.model, status=status,
        solved=solved, expected_flag=ef, flags_reported=flags, duration_s=round(dur, 1),
        cost_usd=round(cost, 4), codex_tokens=tokens, target_url=url, error=err,
    )


async def run_benchmark(bench_id: str, timeout: int, done: set, sem: asyncio.Semaphore) -> None:
    async with sem:
        meta = bench_meta(bench_id)
        loop = asyncio.get_event_loop()
        # build once
        ok, why = await loop.run_in_executor(None, make_build, bench_id)
        if not ok:
            for combo in COMBOS:
                if (bench_id, combo.key) in done:
                    continue
                rr = RunResult(bench_id, meta["name"], meta["level"], meta["tags"], combo.key,
                               combo.backend, combo.model, "BUILD_ERROR", False,
                               expected_flag(bench_id), 0, 0.0, 0.0, 0, "", why[:200])
                append_result(rr)
            print(f"[{bench_id}] BUILD_ERROR: {why[:120]}", flush=True)
            return
        for combo in COMBOS:
            if (bench_id, combo.key) in done:
                print(f"[{bench_id}/{combo.key}] skip (done)", flush=True)
                continue
            # fresh container per combo
            await loop.run_in_executor(None, compose_down, bench_id)
            up_ok, up_why = await loop.run_in_executor(None, compose_up, bench_id)
            url = await loop.run_in_executor(None, discover_url, bench_id) if up_ok else None
            if not up_ok or not url or not await loop.run_in_executor(None, liveness, url):
                rr = RunResult(bench_id, meta["name"], meta["level"], meta["tags"], combo.key,
                               combo.backend, combo.model, "ERROR", False, expected_flag(bench_id),
                               0, 0.0, 0.0, 0, url or "", f"target not up: {up_why}"[:200])
                append_result(rr)
                print(f"[{bench_id}/{combo.key}] target-not-up", flush=True)
                continue
            print(f"[{bench_id}/{combo.key}] running @ {url}", flush=True)
            rr = await run_agent(bench_id, meta, url, combo, timeout)
            append_result(rr)
            print(f"[{bench_id}/{combo.key}] {rr.status} t={rr.duration_s}s "
                  f"cost=${rr.cost_usd} tok={rr.codex_tokens}", flush=True)
        await loop.run_in_executor(None, compose_down, bench_id)


def select_buildable(timeout_build: int) -> list[str]:
    """Build candidates in listed order; return first PILOT_SIZE that build + serve."""
    selected: list[str] = []
    for bid in CANDIDATES:
        if len(selected) >= PILOT_SIZE:
            break
        ok, why = make_build(bid, timeout=timeout_build)
        if not ok:
            print(f"[prepare] {bid}: BUILD_FAIL {why[:100]}", flush=True)
            continue
        up_ok, up_why = compose_up(bid)
        url = discover_url(bid) if up_ok else None
        live = bool(url) and liveness(url)
        compose_down(bid)
        if up_ok and url and live:
            selected.append(bid)
            print(f"[prepare] {bid}: READY ({url})", flush=True)
        else:
            print(f"[prepare] {bid}: NOT_SERVING ({up_why})", flush=True)
    return selected


async def main_run(args: argparse.Namespace) -> None:
    WS_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if args.benchmarks:
        selected = args.benchmarks.split(",")
    else:
        print("=== PREPARE: selecting buildable benchmarks ===", flush=True)
        selected = select_buildable(args.build_timeout)
    (PILOT_DIR / "selected.json").write_text(json.dumps(selected, indent=2))
    print(f"=== SELECTED {len(selected)}: {selected} ===", flush=True)

    done = load_done()
    sem = asyncio.Semaphore(args.concurrency)
    await asyncio.gather(*(run_benchmark(b, args.timeout, done, sem) for b in selected))
    print("=== PILOT COMPLETE ===", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=600, help="per-agent-run timeout (s)")
    ap.add_argument("--build-timeout", type=int, default=900)
    ap.add_argument("--concurrency", type=int, default=2, help="benchmarks in parallel")
    ap.add_argument("--benchmarks", type=str, default="", help="comma list to override selection")
    ap.add_argument("--report", action="store_true", help="only render report from results.jsonl")
    args = ap.parse_args()
    if args.report:
        from report import render  # type: ignore
        render()
        return
    asyncio.run(main_run(args))


if __name__ == "__main__":
    main()
