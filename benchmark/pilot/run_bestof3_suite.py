#!/usr/bin/env python3
"""Run the full best-of-three Docker XBOW comparison suite.

This is a thin orchestration layer over ``run_docker_bench.py``. It keeps the
benchmark logic in one place while making the final comparison reproducible:
canary -> single -> framework -> best-of-3 report.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from report_best_of import (
    EXCLUDED_CLASSES,
    EXCLUDED_STATUSES,
    load_rows,
    render,
    summarize_rows,
)
from run_docker_bench import _ALL_COMBOS, DEFAULT_BENCHMARKS

PGPT_REPO = Path(__file__).resolve().parents[2]
PILOT_DIR = Path(__file__).resolve().parent

DEFAULT_COMBOS = ",".join(combo.key for combo in _ALL_COMBOS)
DEFAULT_BENCHMARK_LIST = ",".join(DEFAULT_BENCHMARKS)


@dataclass(frozen=True)
class SuitePaths:
    run_id: str

    @property
    def canary_single(self) -> Path:
        return PILOT_DIR / f"docker_bof3_{self.run_id}_canary_single.jsonl"

    @property
    def canary_framework(self) -> Path:
        return PILOT_DIR / f"docker_bof3_{self.run_id}_canary_framework.jsonl"

    @property
    def single(self) -> Path:
        return PILOT_DIR / f"docker_bof3_{self.run_id}_single.jsonl"

    @property
    def pipeline(self) -> Path:
        return PILOT_DIR / f"docker_bof3_{self.run_id}_pipeline.jsonl"

    @property
    def framework(self) -> Path:
        return PILOT_DIR / f"docker_bof3_{self.run_id}_framework.jsonl"

    @property
    def report(self) -> Path:
        return PILOT_DIR / f"DOCKER_BEST_OF_3_{self.run_id}.md"


def _quote_cmd(cmd: list[str]) -> str:
    return " ".join(subprocess.list2cmdline([part]) for part in cmd)


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
) -> None:
    print(f"+ (cd {cwd} && {_quote_cmd(cmd)})", flush=True)
    if dry_run:
        return
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def _image_exists(image: str) -> bool:
    return (
        subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _preflight(image: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"+ docker image inspect {image} >/dev/null || make docker-build", flush=True)
        _run(["make", "docker-auth-status", "ROUNDTRIP=1"], cwd=PGPT_REPO, dry_run=True)
        return
    if not _image_exists(image):
        _run(["make", "docker-build"], cwd=PGPT_REPO)
    _run(["make", "docker-auth-status", "ROUNDTRIP=1"], cwd=PGPT_REPO)


def _runner_cmd(
    *,
    variant: str,
    image: str,
    source_root: str,
    benchmarks: str,
    timeout: int,
    concurrency: int,
    max_codex: int,
    attempt: int,
    attempts: int,
    out: Path,
    framework_executor_concurrency: int,
) -> list[str]:
    cmd = [
        "uv",
        "run",
        "python",
        "run_docker_bench.py",
        "--variant",
        variant,
        "--image",
        image,
        "--source-root",
        source_root,
        "--benchmarks",
        benchmarks,
        "--timeout",
        str(timeout),
        "--concurrency",
        str(concurrency),
        "--max-codex",
        str(max_codex),
        "--attempt",
        str(attempt),
        "--attempts",
        str(attempts),
        "--out",
        out.name,
    ]
    if variant == "framework":
        cmd.extend(["--framework-executor-concurrency", str(framework_executor_concurrency)])
    return cmd


def _is_excluded(row: dict) -> bool:
    return row.get("status") in EXCLUDED_STATUSES or row.get("failure_class") in EXCLUDED_CLASSES


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_canary(path: Path, *, benchmarks: str, combos: str, variant: str) -> None:
    rows = _read_jsonl(path)
    if not rows:
        raise SystemExit(f"canary produced no rows: {path}")
    cells = summarize_rows(rows, best_k=1)
    expected = [
        (benchmark, combo, variant)
        for benchmark in _csv_items(benchmarks)
        for combo in _csv_items(combos)
    ]
    missing_or_incomplete = [
        key for key in expected if key not in cells or len(cells[key].used) < 1
    ]
    if missing_or_incomplete:
        details = ", ".join("/".join(key) for key in missing_or_incomplete)
        raise SystemExit(
            "canary has no valid attempt for these cells; rerun with the same "
            f"--run-id after fixing infra/auth issues: {details}"
        )
    print(f"canary ok: {len(expected)} valid cell(s)", flush=True)


def _render_and_validate(
    paths: SuitePaths,
    *,
    best_k: int,
    dry_run: bool,
    benchmarks: str,
    combos: str,
) -> None:
    inputs = [paths.single, paths.framework]
    cmd = [
        "uv",
        "run",
        "python",
        "report_best_of.py",
        "--best-k",
        str(best_k),
        "--output",
        paths.report.name,
        *(path.name for path in inputs),
    ]
    _run(cmd, cwd=PILOT_DIR, dry_run=dry_run)
    if dry_run:
        return

    rows = load_rows(inputs)
    render(rows, best_k=best_k, output=paths.report)
    cells = summarize_rows(rows, best_k=best_k)
    expected_keys = [
        (benchmark, combo, variant)
        for benchmark in _csv_items(benchmarks)
        for combo in _csv_items(combos)
        for variant in ("single", "framework")
    ]
    missing = [key for key in expected_keys if key not in cells]
    incomplete = [cell for cell in cells.values() if not cell.complete]
    if missing:
        sample = ", ".join("/".join(key) for key in missing[:8])
        raise SystemExit(
            "best-of-three report is missing cells; rerun with "
            f"--run-id {paths.run_id}. Examples: {sample}"
        )
    if incomplete:
        sample = ", ".join(
            f"{cell.variant}/{cell.benchmark_id}/{cell.combo}={len(cell.used)}/{best_k}"
            for cell in incomplete[:8]
        )
        raise SystemExit(
            "best-of-three report has incomplete cells; rerun with "
            f"--run-id {paths.run_id}. Examples: {sample}"
        )
    print(f"best-of-three report complete: {paths.report}", flush=True)


def run_suite(args: argparse.Namespace) -> None:
    paths = SuitePaths(args.run_id)
    _preflight(args.image, dry_run=args.dry_run)

    if not args.skip_canary:
        single_canary_env = {**os.environ, "PILOT_COMBOS": args.canary_single_combos}
        _run(
            _runner_cmd(
                variant="single",
                image=args.image,
                source_root=args.source_root,
                benchmarks=args.canary_benchmarks,
                timeout=args.canary_timeout,
                concurrency=min(args.concurrency, 2),
                max_codex=args.max_codex,
                attempt=1,
                attempts=1,
                out=paths.canary_single,
                framework_executor_concurrency=0,
            ),
            cwd=PILOT_DIR,
            env=single_canary_env,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            _validate_canary(
                paths.canary_single,
                benchmarks=args.canary_benchmarks,
                combos=args.canary_single_combos,
                variant="single",
            )

        framework_canary_env = {**os.environ, "PILOT_COMBOS": args.canary_framework_combos}
        _run(
            _runner_cmd(
                variant="framework",
                image=args.image,
                source_root=args.source_root,
                benchmarks=args.canary_benchmarks,
                timeout=args.canary_timeout,
                concurrency=min(args.concurrency, 2),
                max_codex=args.max_codex,
                attempt=1,
                attempts=1,
                out=paths.canary_framework,
                framework_executor_concurrency=args.framework_executor_concurrency,
            ),
            cwd=PILOT_DIR,
            env=framework_canary_env,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            _validate_canary(
                paths.canary_framework,
                benchmarks=args.canary_benchmarks,
                combos=args.canary_framework_combos,
                variant="framework",
            )

    final_env = {**os.environ, "PILOT_COMBOS": args.combos}
    for variant, out in (
        ("single", paths.single),
        ("framework", paths.framework),
    ):
        _run(
            _runner_cmd(
                variant=variant,
                image=args.image,
                source_root=args.source_root,
                benchmarks=args.benchmarks,
                timeout=args.timeout,
                concurrency=args.concurrency,
                max_codex=args.max_codex,
                attempt=args.attempt,
                attempts=args.attempts,
                out=out,
                framework_executor_concurrency=args.framework_executor_concurrency,
            ),
            cwd=PILOT_DIR,
            env=final_env,
            dry_run=args.dry_run,
        )

    _render_and_validate(
        paths,
        best_k=args.attempts,
        dry_run=args.dry_run,
        benchmarks=args.benchmarks,
        combos=args.combos,
    )

    print("\nBest-of-three outputs:", flush=True)
    print(f"  single:    {paths.single}", flush=True)
    print(f"  framework: {paths.framework}", flush=True)
    print(f"  report:    {paths.report}", flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--image", default=os.environ.get("DOCKER_IMAGE", "pentestgpt:latest"))
    parser.add_argument("--source-root", default="../..")
    parser.add_argument("--benchmarks", default=DEFAULT_BENCHMARK_LIST)
    parser.add_argument("--combos", default=DEFAULT_COMBOS)
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-codex", type=int, default=1)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--framework-executor-concurrency", type=int, default=2)
    parser.add_argument("--skip-canary", action="store_true")
    parser.add_argument("--canary-single-combos", default="claude-sonnet,codex-gpt-5.5")
    parser.add_argument("--canary-framework-combos", default="claude-sonnet")
    parser.add_argument("--canary-benchmarks", default="XBEN-068-24,XBEN-080-24")
    parser.add_argument("--canary-timeout", type=int, default=1200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.attempts != 3:
        raise SystemExit("this suite is the final best-of-three runner; keep --attempts 3")
    if args.max_codex != 1:
        raise SystemExit("keep --max-codex 1 unless you intentionally edit the runner")
    run_suite(args)


if __name__ == "__main__":
    main(sys.argv[1:])
