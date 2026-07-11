#!/usr/bin/env python3
"""Render a best-of-k Docker-network benchmark report from append-only JSONL rows."""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from report import COMBO_LABEL, COMBO_ORDER

PILOT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUTS = [
    PILOT_DIR / "docker_bestof3_pipeline.jsonl",
    PILOT_DIR / "docker_bestof3_framework.jsonl",
    PILOT_DIR / "docker_bestof3_single.jsonl",
]
REPORT_MD = PILOT_DIR / "DOCKER_BEST_OF_3.md"

EXCLUDED_STATUSES = {
    "BUILD_ERROR",
    "COMPOSE_UP_ERROR",
    "LIVENESS_ERROR",
    "DOCKER_RUN_ERROR",
    "AUTH_ERROR",
    "PROVIDER_NETWORK_ERROR",
    "EARLY_EXIT",
    "INTERRUPTED",
}
EXCLUDED_CLASSES = {"infra", "auth", "provider_network", "early_exit"}
TRANSIENT_ERROR_MARKERS = (
    "selected model is at capacity",
    "model is at capacity",
)


def load_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row.setdefault("_source", path.name)
            rows.append(row)
    return rows


def row_variant(row: dict) -> str:
    if row.get("variant"):
        return str(row["variant"])
    source = str(row.get("_source", ""))
    if "single" in source:
        return "single"
    if "framework" in source:
        return "framework"
    return "pipeline"


def row_attempt(row: dict) -> int:
    try:
        return int(row.get("attempt") or 1)
    except (TypeError, ValueError):
        return 1


def is_valid_attempt(row: dict) -> bool:
    if row.get("status") in EXCLUDED_STATUSES:
        return False
    if row.get("failure_class") in EXCLUDED_CLASSES:
        return False
    error = str(row.get("error") or "").lower()
    if any(marker in error for marker in TRANSIENT_ERROR_MARKERS):
        return False
    timeout = float(row.get("timeout_s") or 0)
    duration = float(row.get("duration_s") or 0)
    return not (timeout and duration > timeout + 300)


@dataclass
class CellSummary:
    benchmark_id: str
    combo: str
    variant: str
    rows: list[dict]
    valid: list[dict]
    excluded: list[dict]
    best_k: int

    @property
    def used(self) -> list[dict]:
        return self.valid[: self.best_k]

    @property
    def solved(self) -> bool:
        return any(bool(r.get("solved")) for r in self.used)

    @property
    def complete(self) -> bool:
        return len(self.used) >= self.best_k

    @property
    def attempts_to_solve(self) -> int | None:
        for row in self.used:
            if row.get("solved"):
                return row_attempt(row)
        return None

    @property
    def first_solve_time(self) -> float | None:
        for row in self.used:
            if row.get("solved"):
                return float(row.get("duration_s") or 0)
        return None

    @property
    def timeout_count(self) -> int:
        return sum(1 for row in self.used if row.get("status") == "TIMEOUT")

    @property
    def status(self) -> str:
        if self.solved:
            return "SOLVED"
        if not self.complete:
            return "INCOMPLETE"
        return "UNSOLVED"


def summarize_rows(rows: list[dict], best_k: int = 3) -> dict[tuple[str, str, str], CellSummary]:
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (str(row["benchmark_id"]), str(row["combo"]), row_variant(row))
        grouped.setdefault(key, []).append(row)

    out: dict[tuple[str, str, str], CellSummary] = {}
    for (bench_id, combo, variant), group in grouped.items():
        ordered = sorted(group, key=lambda row: (row_attempt(row), str(row.get("_source", ""))))
        valid = [row for row in ordered if is_valid_attempt(row)]
        excluded = [row for row in ordered if not is_valid_attempt(row)]
        out[(bench_id, combo, variant)] = CellSummary(
            benchmark_id=bench_id,
            combo=combo,
            variant=variant,
            rows=ordered,
            valid=valid,
            excluded=excluded,
            best_k=best_k,
        )
    return out


def _pct(num: int, den: int) -> str:
    return "n/a" if den == 0 else f"{100 * num / den:.0f}%"


def _cell_text(cell: CellSummary | None) -> str:
    if cell is None:
        return "."
    solved_attempt = cell.attempts_to_solve
    excl = len(cell.excluded)
    suffix = f", excl={excl}" if excl else ""
    if cell.solved:
        return f"SOLVED a{solved_attempt} ({len(cell.used)}/{cell.best_k} valid{suffix})"
    if cell.complete:
        return f"UNSOLVED ({len(cell.used)}/{cell.best_k} valid, timeouts={cell.timeout_count}{suffix})"
    return f"INCOMPLETE ({len(cell.used)}/{cell.best_k} valid{suffix})"


def render(rows: list[dict], *, best_k: int = 3, output: Path = REPORT_MD) -> str:
    cells = summarize_rows(rows, best_k=best_k)
    if not cells:
        text = "No best-of benchmark rows found.\n"
        output.write_text(text)
        return text

    variant_order = {"pipeline": 0, "single": 1, "framework": 2}
    variants = sorted(
        {variant for (_bench, _combo, variant) in cells},
        key=lambda v: (variant_order.get(v, 99), v),
    )
    combos = [combo for combo in COMBO_ORDER if any(combo == c for (_b, c, _v) in cells)]
    benches = sorted({bench for (bench, _combo, _variant) in cells})
    sources = sorted({str(row.get("_source", "")) for row in rows if row.get("_source")})

    out: list[str] = []
    out.append(f"# PentestGPT Docker best-of-{best_k} XBOW benchmark\n")
    out.append(f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}_\n")
    out.append(
        "Best-of-k solve rates use the first k valid pentest attempts per "
        "(challenge, model, variant). Infra, auth, Docker-run, liveness, and "
        "framework early-exit rows are reported but excluded from the valid-attempt count.\n"
    )
    out.append(f"Inputs: {', '.join(sources) or 'provided rows'}.\n")

    out.append("## Headline by variant and model\n")
    out.append(
        "| Variant | Model | Cells | Complete | Best-of solved | Attempt-1 solved | Timeout rate | Excluded rows | Avg first solve |"
    )
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for variant in variants:
        for combo in combos:
            xs = [cell for (bench, c, v), cell in cells.items() if c == combo and v == variant]
            if not xs:
                continue
            solved = sum(1 for cell in xs if cell.solved)
            complete = sum(1 for cell in xs if cell.complete)
            attempt1 = sum(1 for cell in xs if cell.valid[:1] and cell.valid[0].get("solved"))
            valid_attempts = sum(len(cell.used) for cell in xs)
            timeouts = sum(cell.timeout_count for cell in xs)
            excluded = sum(len(cell.excluded) for cell in xs)
            first_times = [
                cell.first_solve_time for cell in xs if cell.first_solve_time is not None
            ]
            avg_first = f"{statistics.mean(first_times):.0f}s" if first_times else "-"
            out.append(
                f"| {variant} | {COMBO_LABEL.get(combo, combo)} | {len(xs)} | "
                f"{complete}/{len(xs)} | {solved}/{len(xs)} ({_pct(solved, len(xs))}) | "
                f"{attempt1}/{len(xs)} | {timeouts}/{valid_attempts} ({_pct(timeouts, valid_attempts)}) | "
                f"{excluded} | {avg_first} |"
            )

    if {"pipeline", "framework"}.issubset(set(variants)):
        out.append("\n## Pipeline vs framework head-to-head\n")
        out.append("| Model | Common cells | Pipeline solved | Framework solved | Delta |")
        out.append("|---|---:|---:|---:|---:|")
        for combo in combos:
            common = [
                bench
                for bench in benches
                if (bench, combo, "pipeline") in cells and (bench, combo, "framework") in cells
            ]
            if not common:
                continue
            ps = sum(1 for bench in common if cells[(bench, combo, "pipeline")].solved)
            fs = sum(1 for bench in common if cells[(bench, combo, "framework")].solved)
            delta = fs - ps
            out.append(
                f"| {COMBO_LABEL.get(combo, combo)} | {len(common)} | {ps} | {fs} | {delta:+d} |"
            )

    out.append("\n## Per-challenge cells\n")
    for variant in variants:
        out.append(f"\n### {variant}\n")
        out.append(
            "| Challenge | " + " | ".join(COMBO_LABEL.get(combo, combo) for combo in combos) + " |"
        )
        out.append("|" + "---|" * (1 + len(combos)))
        for bench in benches:
            parts = [_cell_text(cells.get((bench, combo, variant))) for combo in combos]
            out.append(f"| {bench} | " + " | ".join(parts) + " |")

    out.append("\n## Methodology\n")
    out.append(
        f"- Best-of-{best_k} counts a cell solved if any of the first {best_k} valid attempts reports the expected flag.\n"
        "- Valid attempts include solved, unsolved, timeout, and launched tool-error rows.\n"
        "- Excluded rows include build, compose, liveness, Docker-run, auth, and framework early-exit failures.\n"
        "- Timeout rate is computed over valid attempts used in the best-of-k window.\n"
    )

    text = "\n".join(out) + "\n"
    output.write_text(text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--best-k", type=int, default=3)
    parser.add_argument("--output", type=Path, default=REPORT_MD)
    parser.add_argument("inputs", nargs="*", type=Path, help="JSONL result files")
    args = parser.parse_args()
    inputs = args.inputs or DEFAULT_INPUTS
    print(render(load_rows(inputs), best_k=args.best_k, output=args.output))


if __name__ == "__main__":
    main()
