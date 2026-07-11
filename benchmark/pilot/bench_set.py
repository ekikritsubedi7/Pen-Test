#!/usr/bin/env python3
"""Toggleable XBOW benchmark sets + an agent-friendly runner.

This is a thin layer over ``run_docker_bench.py``. It reads
``benchmark_sets.json`` -- a registry of *named* challenge sets, where each
challenge carries an ``enabled`` toggle -- and drives the underlying Docker
runner against the enabled challenges only.

Designed so another agent (or a human) can, with minimal ceremony:

    # see the set and its toggle state (``--json`` for machine parsing)
    python bench_set.py list --set hard-open
    # flip individual challenges on/off (persists to benchmark_sets.json)
    python bench_set.py disable XBEN-057-24 XBEN-101-24
    python bench_set.py enable XBEN-057-24
    # print just the enabled comma-list (composes with other make targets)
    python bench_set.py ids --set hard-open
    # run: auto-suggests parallelism, or pass an explicit --concurrency N
    python bench_set.py run --set hard-open --variant framework --concurrency auto

Docker is triggered entirely inside ``run_docker_bench.py`` (``make build`` ->
``docker compose up`` -> discover target IP -> ``docker run`` the tool image ->
score -> teardown). This wrapper only selects challenges, resolves ``XBEN_ROOT``,
picks parallelism, and shells out.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PILOT_DIR = Path(__file__).resolve().parent
PGPT_REPO = PILOT_DIR.parents[1]
SETS_PATH = PILOT_DIR / "benchmark_sets.json"

# Keep combo keys / default image in sync with the runner when importable;
# fall back to literals so `list`/`ids`/`enable`/`disable` work even if the
# runner import breaks (e.g. a missing optional dep in a minimal env).
try:
    sys.path.insert(0, str(PILOT_DIR))
    from run_docker_bench import _ALL_COMBOS, DEFAULT_IMAGE  # type: ignore

    VALID_COMBOS = [c.key for c in _ALL_COMBOS]
except Exception:  # pragma: no cover - defensive fallback
    VALID_COMBOS = ["claude-opus", "claude-sonnet", "codex-gpt-5.5", "codex-gpt-5.4-mini"]
    DEFAULT_IMAGE = os.environ.get("DOCKER_IMAGE", "pentestgpt:latest")

DEFAULT_SET = "hard-open"
DEFAULT_VARIANT = "framework"
DEFAULT_COMBOS = ",".join(VALID_COMBOS)
BASE_CONCURRENCY = 2  # README: "Start real sweeps at --concurrency 2".

# XBEN_ROOT resolution: env wins, then any of these known checkouts that exists.
# The old run_docker_bench.py default path is dead; the cochise checkout is live.
XBEN_ROOT_CANDIDATES = [
    "/Users/gelei/papers/cochise/xbow-benchmarks/benchmarks",
    "/Users/gelei/Research/PentestGPTClaude/benchmark/xbow-validation-benchmarks/benchmarks",
]


# --- registry helpers (pure; unit-tested without Docker) -------------------
def load_registry(path: Path = SETS_PATH) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise SystemExit(f"benchmark set registry not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"benchmark set registry is not valid JSON ({path}): {exc}") from None


def save_registry(reg: dict, path: Path = SETS_PATH) -> None:
    Path(path).write_text(json.dumps(reg, indent=2) + "\n")


def get_set(reg: dict, name: str) -> dict:
    if name not in reg:
        known = ", ".join(sorted(reg)) or "(none)"
        raise SystemExit(f"unknown benchmark set '{name}'. known sets: {known}")
    return reg[name]


def challenges(set_obj: dict) -> list[dict]:
    return set_obj.get("challenges", [])


def enabled_ids(set_obj: dict) -> list[str]:
    return [c["id"] for c in challenges(set_obj) if c.get("enabled")]


def set_enabled(set_obj: dict, ids: list[str], value: bool) -> tuple[list[str], list[str]]:
    """Flip ``enabled`` for the given ids. ``["all"]`` targets every challenge.

    Returns (changed_ids, unknown_ids). Idempotent: ids already at ``value`` are
    not reported as changed.
    """
    by_id = {c["id"]: c for c in challenges(set_obj)}
    if ids == ["all"]:
        targets = list(by_id)
        unknown: list[str] = []
    else:
        targets = [i for i in ids if i in by_id]
        unknown = [i for i in ids if i not in by_id]
    changed = []
    for i in targets:
        if by_id[i].get("enabled") != value:
            by_id[i]["enabled"] = value
            changed.append(i)
    return changed, unknown


# --- environment / parallelism helpers -------------------------------------
def resolve_xben_root(explicit: str | None = None) -> Path:
    """Resolve the XBOW fixtures checkout: --xben-root > $XBEN_ROOT > candidates."""
    ordered = [explicit, os.environ.get("XBEN_ROOT"), *XBEN_ROOT_CANDIDATES]
    for cand in ordered:
        if cand and Path(cand).is_dir():
            return Path(cand)
    checked = "\n  ".join(c for c in ordered if c)
    raise SystemExit(
        "could not locate an XBOW fixtures checkout. Set XBEN_ROOT or pass "
        "--xben-root to a directory of XBEN-*-24 challenge dirs.\nchecked:\n  " + checked
    )


def missing_dirs(root: Path, ids: list[str]) -> list[str]:
    return [i for i in ids if not (root / i).is_dir()]


def suggest_concurrency(enabled_count: int) -> int:
    return max(1, min(enabled_count, BASE_CONCURRENCY))


def resolve_concurrency(value: str, enabled_count: int) -> int:
    if str(value).lower() == "auto":
        return suggest_concurrency(enabled_count)
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise SystemExit(
            f"--concurrency must be 'auto' or a positive integer, got {value!r}"
        ) from None
    if n < 1:
        raise SystemExit(f"--concurrency must be >= 1, got {n}")
    return n


def variants_for(variant: str) -> list[str]:
    if variant == "both":
        return ["single", "framework"]
    return [variant]


def default_out(variant: str, set_name: str) -> str:
    return f"docker_{variant}_{set_name}.jsonl"


def build_runner_cmd(
    *,
    variant: str,
    benchmarks: str,
    concurrency: int,
    timeout: int,
    attempt: int,
    attempts: int,
    max_codex: int,
    image: str,
    source_root: str,
    framework_executor_concurrency: int,
    out: str,
) -> list[str]:
    cmd = [
        "uv", "run", "python", "run_docker_bench.py",
        "--variant", variant,
        "--image", image,
        "--benchmarks", benchmarks,
        "--timeout", str(timeout),
        "--concurrency", str(concurrency),
        "--max-codex", str(max_codex),
        "--attempt", str(attempt),
        "--attempts", str(attempts),
        "--out", out,
    ]
    if source_root:
        cmd += ["--source-root", source_root]
    if variant == "framework":
        cmd += ["--framework-executor-concurrency", str(framework_executor_concurrency)]
    return cmd


def _quote(cmd: list[str]) -> str:
    return " ".join(subprocess.list2cmdline([part]) for part in cmd)


# --- command handlers ------------------------------------------------------
def cmd_list(args) -> int:
    reg = load_registry(args.sets_file)
    set_obj = get_set(reg, args.set)
    chs = challenges(set_obj)
    if args.json:
        print(json.dumps({"set": args.set, **set_obj}, indent=2))
        return 0
    en = enabled_ids(set_obj)
    print(f"set: {args.set}  ({len(en)}/{len(chs)} enabled)")
    print(f"  {set_obj.get('description', '')}")
    print(f"  variant_default: {set_obj.get('variant_default', DEFAULT_VARIANT)}")
    print()
    header = f"  {'ID':<13} {'LVL':<3} {'ON':<3} {'FW':<3} {'TAGS':<28} NOTE"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for c in chs:
        on = "on" if c.get("enabled") else "off"
        fw = "yes" if c.get("solved_by_framework") else "no"
        tags = ",".join(c.get("tags", []))
        print(
            f"  {c['id']:<13} {c.get('level', '?')!s:<3} {on:<3} {fw:<3} "
            f"{tags:<28} {c.get('note', '')}"
        )
    return 0


def cmd_ids(args) -> int:
    reg = load_registry(args.sets_file)
    set_obj = get_set(reg, args.set)
    print(",".join(enabled_ids(set_obj)))
    return 0


def cmd_toggle(args, value: bool) -> int:
    reg = load_registry(args.sets_file)
    set_obj = get_set(reg, args.set)
    changed, unknown = set_enabled(set_obj, args.ids, value)
    if unknown:
        raise SystemExit(f"unknown challenge id(s) in set '{args.set}': {', '.join(unknown)}")
    save_registry(reg, args.sets_file)
    word = "enabled" if value else "disabled"
    if changed:
        print(f"{word}: {', '.join(changed)}")
    else:
        print(f"no change (already {word})")
    print(f"now {len(enabled_ids(set_obj))}/{len(challenges(set_obj))} enabled in '{args.set}'")
    return 0


def plan_run(args) -> dict:
    """Resolve everything needed to run, without executing. Pure enough to test."""
    reg = load_registry(args.sets_file)
    set_obj = get_set(reg, args.set)
    ids = enabled_ids(set_obj)
    if not ids:
        raise SystemExit(f"no enabled challenges in set '{args.set}' -- nothing to run")

    variant = args.variant or set_obj.get("variant_default", DEFAULT_VARIANT)
    for combo in [c.strip() for c in args.combos.split(",") if c.strip()]:
        if combo not in VALID_COMBOS:
            raise SystemExit(f"unknown combo '{combo}'. valid: {', '.join(VALID_COMBOS)}")

    root = resolve_xben_root(args.xben_root)
    concurrency = resolve_concurrency(args.concurrency, len(ids))
    benchmarks = ",".join(ids)
    cmds = [
        build_runner_cmd(
            variant=v,
            benchmarks=benchmarks,
            concurrency=concurrency,
            timeout=args.timeout,
            attempt=args.attempt,
            attempts=args.attempts,
            max_codex=args.max_codex,
            image=args.image,
            source_root=args.source_root,
            framework_executor_concurrency=args.framework_executor_concurrency,
            out=args.out or default_out(v, args.set),
        )
        for v in variants_for(variant)
    ]
    return {
        "set": args.set,
        "variant": variant,
        "combos": args.combos,
        "enabled_ids": ids,
        "xben_root": str(root),
        "missing_dirs": missing_dirs(root, ids),
        "cpu_cores": os.cpu_count(),
        "concurrency": concurrency,
        "concurrency_auto": str(args.concurrency).lower() == "auto",
        "commands": cmds,
    }


def cmd_run(args) -> int:
    plan = plan_run(args)
    auto_hint = " (auto; scale toward 4 after a clean small matrix)" if plan["concurrency_auto"] else ""

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(f"benchmark set : {plan['set']}")
        print(f"XBEN_ROOT     : {plan['xben_root']}")
        print(f"variants      : {', '.join(variants_for(plan['variant']))}")
        print(f"combos        : {plan['combos']}")
        print(f"enabled ({len(plan['enabled_ids'])}) : {','.join(plan['enabled_ids'])}")
        print(
            f"host          : {plan['cpu_cores']} CPU cores | "
            f"--concurrency {plan['concurrency']}{auto_hint}"
        )
        print(
            "note          : each parallel slot ~= 1 target stack + 1 tool container; "
            "heavy amd64-emulated images are costly."
        )
        print()

    if plan["missing_dirs"]:
        msg = (
            f"{len(plan['missing_dirs'])} enabled challenge dir(s) missing under "
            f"{plan['xben_root']}: {', '.join(plan['missing_dirs'])}"
        )
        if not args.dry_run and not args.allow_missing:
            raise SystemExit("ERROR: " + msg + "\n(pass --allow-missing to run anyway)")
        print("WARNING: " + msg)

    env = {**os.environ, "PILOT_COMBOS": args.combos, "XBEN_ROOT": plan["xben_root"]}
    for cmd in plan["commands"]:
        print(f"+ (cd {PILOT_DIR} && {_quote(cmd)})", flush=True)
        if args.dry_run:
            continue
        subprocess.run(cmd, cwd=str(PILOT_DIR), env=env, check=True)
    return 0


# --- argument parsing ------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--set", default=DEFAULT_SET, help=f"named set in the registry (default {DEFAULT_SET})")
    common.add_argument(
        "--sets-file", type=Path, default=SETS_PATH, help="path to the benchmark set registry JSON"
    )

    p_list = sub.add_parser("list", parents=[common], help="show a set and its toggle state")
    p_list.add_argument("--json", action="store_true", help="emit the raw set object as JSON")
    p_list.set_defaults(func=cmd_list)

    p_ids = sub.add_parser("ids", parents=[common], help="print the enabled challenge ids (comma-separated)")
    p_ids.set_defaults(func=cmd_ids)

    p_en = sub.add_parser("enable", parents=[common], help="enable challenge id(s) (or 'all')")
    p_en.add_argument("ids", nargs="+")
    p_en.set_defaults(func=lambda a: cmd_toggle(a, True))

    p_dis = sub.add_parser("disable", parents=[common], help="disable challenge id(s) (or 'all')")
    p_dis.add_argument("ids", nargs="+")
    p_dis.set_defaults(func=lambda a: cmd_toggle(a, False))

    p_run = sub.add_parser("run", parents=[common], help="run the enabled challenges via run_docker_bench.py")
    p_run.add_argument("--variant", choices=["framework", "single", "both"], default=None,
                       help="default: the set's variant_default (hard-open -> framework)")
    p_run.add_argument("--concurrency", default="auto",
                       help="'auto' (host-aware suggestion) or a positive integer")
    p_run.add_argument("--combos", default=DEFAULT_COMBOS, help="comma list of model/runtime combos")
    p_run.add_argument("--timeout", type=int, default=2400, help="per-agent-run timeout (seconds)")
    p_run.add_argument("--attempt", type=int, default=1)
    p_run.add_argument("--attempts", type=int, default=1)
    p_run.add_argument("--max-codex", type=int, default=1)
    p_run.add_argument("--framework-executor-concurrency", type=int, default=2)
    p_run.add_argument("--image", default=DEFAULT_IMAGE)
    p_run.add_argument("--source-root", default="../..",
                       help="checkout mounted at /app so local Python changes apply without rebuild")
    p_run.add_argument("--out", default="", help="override output JSONL (default docker_<variant>_<set>.jsonl)")
    p_run.add_argument("--xben-root", default=None, help="override XBOW fixtures checkout path")
    p_run.add_argument("--allow-missing", action="store_true", help="run even if some fixture dirs are absent")
    p_run.add_argument("--dry-run", action="store_true", help="print the plan + commands; run nothing")
    p_run.add_argument("--json", action="store_true", help="emit the resolved run plan as JSON")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
