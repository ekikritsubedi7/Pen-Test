#!/usr/bin/env python3
"""Render the Docker-network agent comparison report (DOCKER_COMPARISON.md).

Joins docker-network result sets by (benchmark_id, combo):
  - pipeline : the full 3-stage `pentestgpt` CTF pipeline
               (docker_results.jsonl, the canonical baseline; or
               docker_pipeline_results.jsonl if you refreshed it via run_docker_bench.py).
  - single   : the "pure single agent" baseline (docker_single_results.jsonl).
  - framework: the next-gen `pentestgpt_agent` instructor/executor/judge framework
               (docker_framework_results.jsonl and framework-tagged docker_repeats.jsonl rows,
               when present).

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
FRAMEWORK_JSONL = PILOT_DIR / "docker_framework_results.jsonl"
REPEATS_JSONL = PILOT_DIR / "docker_repeats.jsonl"
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


def _framework_rows() -> list[dict]:
    rows = _load(FRAMEWORK_JSONL)
    rows.extend(r for r in _load(REPEATS_JSONL) if r.get("variant") == "framework")
    return rows


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
    framework = _by_bc(_framework_rows())
    if not single:
        print(f"no single-agent results yet — run: uv run python {Path(__file__).name.replace('report_comparison','run_docker_bench')} --variant single")
        return

    variants = [("pipeline", pipe), ("single", single)]
    if framework:
        variants.append(("framework", framework))

    all_keys = set().union(*(set(src) for _label, src in variants))
    benches = sorted({b for (b, _c) in all_keys})
    combos = [c for c in COMBO_ORDER if any(c == cc for (_b, cc) in all_keys)]
    meta_of = {
        b: next((src[(b, c)] for c in combos for _label, src in variants if (b, c) in src), None)
        for b in benches
    }

    out: list[str] = []
    out.append("# PentestGPT — pipeline vs. single vs. framework (xbow, Docker network)\n")
    out.append(f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}_\n")
    out.append(
        "Does the 3-stage **PentestGPT pipeline** (recon → exploit → walkthrough) beat handing "
        "the same target to a **single, un-orchestrated agent**, or to the next-gen "
        "`pentestgpt_agent` **framework**? Variants use the same targets, Docker-network wiring, "
        "timeout, and flag scoring. The framework score is based on stdout, generated "
        "`report.md`, and judge-accepted ledger findings, not raw executor logs.\n")

    # --- headline: head-to-head solve rates ---
    out.append("## Headline — solve rate (head-to-head subsets)\n")
    out.append(
        "Pipeline vs. single is computed on their full shared non-infra set. Framework columns use "
        "the smaller pipeline/framework overlap when framework rows are present.\n")
    out.append("| Model | Pipe/single n | Pipeline solved | Single solved | Pipe-single | Framework n | Framework solved | Framework-pipe |")
    out.append("|---|---|---|---|---|---|---|---|")
    for c in combos:
        ps_common = [b for b in benches
                     if (b, c) in pipe and (b, c) in single
                     and not is_infra(pipe[(b, c)]) and not is_infra(single[(b, c)])]
        n = len(ps_common)
        if n:
            ps = sum(1 for b in ps_common if pipe[(b, c)]["solved"])
            ss = sum(1 for b in ps_common if single[(b, c)]["solved"])
            pipe_single = ps - ss
            pipe_s = f"{ps}/{n} ({100*ps/n:.0f}%)"
            single_s = f"{ss}/{n} ({100*ss/n:.0f}%)"
        else:
            ps = ss = pipe_single = 0
            pipe_s = single_s = "—"
        ps_sign = f"+{pipe_single}" if pipe_single > 0 else str(pipe_single)
        fw_common = [b for b in benches
                     if framework and (b, c) in pipe and (b, c) in framework
                     and not is_infra(pipe[(b, c)]) and not is_infra(framework[(b, c)])]
        if fw_common:
            f_n = len(fw_common)
            fp = sum(1 for b in fw_common if pipe[(b, c)]["solved"])
            fs = sum(1 for b in fw_common if framework[(b, c)]["solved"])
            framework_pipe = fs - fp
            fp_sign = f"+{framework_pipe}" if framework_pipe > 0 else str(framework_pipe)
            fw_n_s = str(f_n)
            fw_s = f"{fs}/{f_n} ({100*fs/f_n:.0f}%)"
        else:
            fw_n_s = "0" if framework else "—"
            fw_s = "—"
            fp_sign = "—"
        out.append(f"| {COMBO_LABEL[c]} | {n} | {pipe_s} | {single_s} | {ps_sign} | "
                   f"{fw_n_s} | {fw_s} | {fp_sign} |")

    # --- cost / effort per variant ---
    out.append("\n## Cost & effort by model (all runnable runs)\n")
    out.append("| Model | Variant | Solved | Avg time (solved) | Claude $ | Codex tokens |")
    out.append("|---|---|---|---|---|---|")
    for c in combos:
        for label, src in variants:
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
    out.append("\n## Per-challenge\n")
    out.append("Each cell is `pipeline / single` or `pipeline / single / framework` when framework rows exist; "
               "✅ solved / ❌ unsolved / ⏱ timeout / ⚠️ error / 🔧 infra / · not run.\n")
    header = "| Challenge | Lvl | " + " | ".join(COMBO_LABEL[c] for c in combos) + " |"
    out.append(header)
    out.append("|" + "---|" * (2 + len(combos)))
    for b in benches:
        m = meta_of.get(b)
        if not m:
            continue
        cells = []
        for c in combos:
            parts = [_cell(pipe.get((b, c))), _cell(single.get((b, c)))]
            if framework:
                parts.append(_cell(framework.get((b, c))))
            cells.append(" / ".join(parts))
        out.append(f"| {b} | {m['level']} | " + " | ".join(cells) + " |")

    out.append("\n## Methodology\n")
    out.append(
        "- **Pipeline**: `pentestgpt --mode ctf` — 3 fresh agents (recon → DFS exploit → walkthrough).\n"
        "- **Single**: one bare `claude -p` (`--output-format stream-json`) or `codex exec --json` "
        "call, fed `ctf_single_agent_{system,task}_prompt` (the same fragments the pipeline uses, "
        "collapsed into one turn). No orchestration, no inter-stage context handoff.\n"
        "- **Framework**: `python3 -m pentestgpt_agent` — instructor/executor/judge with a durable "
        "ledger. Scored from stdout, generated `report.md`, and judge-accepted ledger findings; "
        "unaccepted raw executor logs do not count.\n"
        "- **Scoring**: the ground-truth flag `FLAG{sha256(UPPER-DIR)}` must appear in the agent's "
        "reported output (`assistant` text for pipeline/single; final report for framework), "
        "not raw tool output.\n"
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
