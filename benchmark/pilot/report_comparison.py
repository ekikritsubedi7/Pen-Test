#!/usr/bin/env python3
"""Render the pipeline-vs-single-agent comparison report (DOCKER_COMPARISON.md).

Joins two docker-network result sets by (benchmark_id, combo):
  - pipeline : the full 3-stage `pentestgpt` CTF pipeline
               (docker_results.jsonl, the canonical baseline; or
               docker_pipeline_results.jsonl if you refreshed it via run_docker_bench.py).
  - single   : the "pure single agent" baseline (docker_single_results.jsonl).

The headline solve rates are computed on the *head-to-head* set — the benchmarks
where BOTH variants produced a real (non-infra) run for that model — so the two
columns are strictly comparable. This isolates the value of the multi-stage
orchestration, since prompt content and everything else is held constant.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from report import COMBO_LABEL, COMBO_ORDER, MARK, is_infra  # reuse the baseline report's helpers

PILOT_DIR = Path(__file__).resolve().parent
SINGLE_JSONL = PILOT_DIR / "docker_single_results.jsonl"
PIPELINE_CANDIDATES = [PILOT_DIR / "docker_results.jsonl", PILOT_DIR / "docker_pipeline_results.jsonl"]
REPORT_MD = PILOT_DIR / "DOCKER_COMPARISON.md"


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _by_bc(rows: list[dict]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        out[(r["benchmark_id"], r["combo"])] = r  # last write wins (handles re-runs)
    return out


def _pipeline_rows() -> list[dict]:
    for path in PIPELINE_CANDIDATES:
        rows = _load(path)
        if rows:
            return rows
    return []


def _cell(r: dict | None) -> str:
    if r is None:
        return "·"
    if is_infra(r):
        return "🔧"
    if r["status"] in ("SOLVED", "UNSOLVED", "TIMEOUT"):
        return f"{MARK.get(r['status'], '?')} {int(r['duration_s'])}s"
    return MARK.get(r["status"], "?")


def render() -> None:
    pipe = _by_bc(_pipeline_rows())
    single = _by_bc(_load(SINGLE_JSONL))
    if not single:
        print(f"no single-agent results yet — run: uv run python {Path(__file__).name.replace('report_comparison','run_docker_bench')} --variant single")
        return

    benches = sorted({b for (b, _c) in pipe} | {b for (b, _c) in single})
    combos = [c for c in COMBO_ORDER if any(c == cc for (_b, cc) in {*pipe, *single})]
    meta_of = {b: (pipe.get((b, c)) or single.get((b, c))) for b in benches for c in combos if (pipe.get((b, c)) or single.get((b, c)))}

    out: list[str] = []
    out.append("# PentestGPT — pipeline vs. pure single-agent (xbow, Docker network)\n")
    out.append(f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}_\n")
    out.append(
        "Does the 3-stage **PentestGPT pipeline** (recon → exploit → walkthrough) beat handing "
        "the same target to a **single, un-orchestrated agent**? Both variants run the *same* "
        "models, targets, Docker-network wiring, timeout, and flag scoring. The single agent is a "
        "literal one-shot `claude -p` / `codex exec` call fed a prompt assembled from PentestGPT's "
        "own prompt fragments — so prompt *content* is held constant and the only variable is the "
        "multi-stage decomposition.\n")

    # --- headline: head-to-head solve rates ---
    out.append("## Headline — solve rate (head-to-head subset)\n")
    out.append(
        "Computed only on benchmarks where **both** variants produced a real (non-infra) run for "
        "that model, so the two columns are strictly comparable.\n")
    out.append("| Model | n | Pipeline solved | Single solved | Delta (pipe - single) |")
    out.append("|---|---|---|---|---|")
    for c in combos:
        common = [b for b in benches
                  if (b, c) in pipe and (b, c) in single
                  and not is_infra(pipe[(b, c)]) and not is_infra(single[(b, c)])]
        n = len(common)
        if not n:
            out.append(f"| {COMBO_LABEL[c]} | 0 | — | — | — |")
            continue
        ps = sum(1 for b in common if pipe[(b, c)]["solved"])
        ss = sum(1 for b in common if single[(b, c)]["solved"])
        delta = ps - ss
        sign = f"+{delta}" if delta > 0 else str(delta)
        out.append(f"| {COMBO_LABEL[c]} | {n} | {ps}/{n} ({100*ps/n:.0f}%) | "
                   f"{ss}/{n} ({100*ss/n:.0f}%) | {sign} |")

    # --- cost / effort per variant ---
    out.append("\n## Cost & effort by model (all runnable runs)\n")
    out.append("| Model | Variant | Solved | Avg time (solved) | Claude $ | Codex tokens |")
    out.append("|---|---|---|---|---|---|")
    for c in combos:
        for label, src in (("pipeline", pipe), ("single", single)):
            rs = [src[(b, c)] for b in benches if (b, c) in src and not is_infra(src[(b, c)])]
            if not rs:
                out.append(f"| {COMBO_LABEL[c]} | {label} | — | — | — | — |")
                continue
            solved = [r for r in rs if r["solved"]]
            avg_t = (sum(r["duration_s"] for r in solved) / len(solved)) if solved else 0
            cost = sum(r.get("cost_usd", 0) for r in rs)
            toks = sum(r.get("codex_tokens", 0) for r in rs)
            cost_s = f"${cost:.2f}" if cost else "—"
            toks_s = f"{toks:,}" if toks else "—"
            out.append(f"| {COMBO_LABEL[c]} | {label} | {len(solved)}/{len(rs)} | "
                       f"{avg_t:.0f}s | {cost_s} | {toks_s} |")

    # --- per-challenge grid (pipeline / single) ---
    out.append("\n## Per-challenge (pipeline / single)\n")
    out.append("Each cell is `pipeline / single`; ✅ solved / ❌ unsolved / ⏱ timeout / "
               "⚠️ error / 🔧 infra / · not run.\n")
    header = "| Challenge | Lvl | " + " | ".join(COMBO_LABEL[c] for c in combos) + " |"
    out.append(header)
    out.append("|" + "---|" * (2 + len(combos)))
    for b in benches:
        m = meta_of.get(b)
        if not m:
            continue
        cells = [f"{_cell(pipe.get((b, c)))} / {_cell(single.get((b, c)))}" for c in combos]
        out.append(f"| {b} | {m['level']} | " + " | ".join(cells) + " |")

    out.append("\n## Methodology\n")
    out.append(
        "- **Pipeline**: `pentestgpt --mode ctf` — 3 fresh agents (recon → DFS exploit → walkthrough).\n"
        "- **Single**: one bare `claude -p` (`--output-format stream-json`) or `codex exec --json` "
        "call, fed `ctf_single_agent_{system,task}_prompt` (the same fragments the pipeline uses, "
        "collapsed into one turn). No orchestration, no inter-stage context handoff.\n"
        "- **Scoring**: the ground-truth flag `FLAG{sha256(UPPER-DIR)}` must appear in the agent's "
        "*assistant text* (not raw tool output) — identical for both variants and both runtimes.\n"
        "- **Wiring**: target via Docker Compose on an internal bridge; the tool image is `docker "
        "run` on that network and attacks the container IP (`172.x`) directly. Per-run timeout, "
        "fresh workspace, results recorded per (challenge, model, variant).\n"
        "- **Cost**: Claude bills per-token (API $); Codex runs on a ChatGPT subscription "
        "(marginal $0), so token counts are shown instead.\n")

    text = "\n".join(out) + "\n"
    REPORT_MD.write_text(text)
    print(text)


if __name__ == "__main__":
    render()
