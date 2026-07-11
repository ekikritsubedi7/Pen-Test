#!/usr/bin/env python3
"""Render the pilot performance report (markdown) from results.jsonl."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

PILOT_DIR = Path(__file__).resolve().parent
RESULTS_JSONL = PILOT_DIR / "results.jsonl"
REPORT_MD = PILOT_DIR / "REPORT.md"

COMBO_ORDER = ["claude-opus", "claude-sonnet", "codex-gpt-5.5", "codex-gpt-5.4-mini"]
COMBO_LABEL = {
    "claude-opus": "Claude Opus",
    "claude-sonnet": "Claude Sonnet",
    "codex-gpt-5.5": "Codex gpt-5.5",
    "codex-gpt-5.4-mini": "Codex gpt-5.4-mini",
}
MARK = {
    "SOLVED": "✅",
    "UNSOLVED": "❌",
    "TIMEOUT": "⏱",
    "ERROR": "⚠️",
    "EARLY_EXIT": "↯",
    "BUILD_ERROR": "🔧",
    "COMPOSE_UP_ERROR": "🔧",
    "LIVENESS_ERROR": "🔧",
    "DOCKER_RUN_ERROR": "🔧",
    "AUTH_ERROR": "🔐",
    "INTERRUPTED": "🔧",
}

_INFRA_KEYS = ("not up", "up-failed", "up-timeout", "build", "manifest", "target not")
_INFRA_STATUSES = {"BUILD_ERROR", "COMPOSE_UP_ERROR", "LIVENESS_ERROR", "DOCKER_RUN_ERROR", "AUTH_ERROR", "INTERRUPTED"}


def is_infra(r: dict) -> bool:
    """True if the run never reached the agent (build/boot/docker failure) — these
    are infrastructure problems, not tool failures, so they are excluded from
    solve-rate denominators rather than counted as a model miss."""
    if r.get("status") in _INFRA_STATUSES:
        return True
    if r.get("failure_class") in {"infra", "auth", "early_exit"}:
        return True
    if r["status"] == "ERROR":
        return any(k in (r.get("error", "") or "").lower() for k in _INFRA_KEYS)
    return False


def _load() -> list[dict]:
    if not RESULTS_JSONL.exists():
        return []
    rows = []
    for line in RESULTS_JSONL.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def render() -> None:
    rows = _load()
    if not rows:
        print("no results yet")
        return

    by_bc: dict[tuple[str, str], dict] = {}
    for r in rows:
        by_bc[(r["benchmark_id"], r["combo"])] = r  # last write wins

    benches = sorted({r["benchmark_id"] for r in rows})
    combos = [c for c in COMBO_ORDER if any(r["combo"] == c for r in rows)]

    n_bench = len(benches)
    # a benchmark is "excluded" only if EVERY combo on it was an infra failure
    infra_bench = sorted(
        b for b in benches
        if all(is_infra(by_bc[(b, c)]) for c in combos if (b, c) in by_bc)
    )
    runnable_bench = [b for b in benches if b not in infra_bench]

    out: list[str] = []
    out.append("# PentestGPT — xbow validation-benchmarks performance pilot\n")
    out.append(f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}_\n")
    out.append(
        "Performance of the autonomous **PentestGPT CTF pipeline** (recon → exploit → "
        "walkthrough) on a representative sample of **medium (L2) / hard (L3)** challenges "
        "from the [xbow-engineering/validation-benchmarks]"
        "(https://github.com/xbow-engineering/validation-benchmarks), comparing four "
        "model/runtime combinations driven through the *same* pipeline.\n")
    out.append("## Models compared\n")
    out.append("| Combo | Runtime | Model | Billing |")
    out.append("|---|---|---|---|")
    out.append("| Claude Opus | Claude Code CLI (`claude -p`) | `opus` (latest, Opus 4.x) | API $ |")
    out.append("| Claude Sonnet | Claude Code CLI (`claude -p`) | `sonnet` (latest, Sonnet 4.x) | API $ |")
    out.append("| Codex gpt-5.5 | OpenAI Codex (`app-server` SDK) | `gpt-5.5` | ChatGPT sub (tokens) |")
    out.append("| Codex gpt-5.4-mini | OpenAI Codex (`app-server` SDK) | `gpt-5.4-mini` | ChatGPT sub (tokens) |")
    out.append(
        f"\nSample: **{len(runnable_bench)} runnable challenges** "
        f"({n_bench} attempted, {len(infra_bench)} excluded for infrastructure failure). "
        "Each cell is one full pipeline run; ✅ solved / ❌ unsolved / ⏱ timeout / "
        "⚠️ tool-error / 🔧 infra-excluded, with wall-clock seconds.\n")

    expected = len(benches) * len(combos)
    recorded = sum(1 for b in benches for c in combos if (b, c) in by_bc)
    if recorded < expected:
        out.append(
            f"\n> ⚠️ **PARTIAL RUN — terminated early.** This is **not** the full medium/hard "
            f"sweep. {recorded} of {expected} (challenge x model) runs executed before the pilot "
            f"was deliberately stopped (the agents' active scans/exploits were tripping local "
            f"endpoint-security monitoring). Cells marked `·` never ran, so per-model denominators "
            f"differ — use the **fully-covered subset** below for the strictly comparable numbers.\n")

    out.append("## Per-challenge results\n")
    header = "| Challenge | Lvl | Category | " + " | ".join(COMBO_LABEL[c] for c in combos) + " |"
    sep = "|" + "---|" * (3 + len(combos))
    out.append(header)
    out.append(sep)
    for b in benches:
        meta = next((by_bc[(b, c)] for c in combos if (b, c) in by_bc), None)
        if not meta:
            continue
        lvl = meta["level"]
        cats = ",".join(meta["tags"][:2])
        cells = []
        for c in combos:
            r = by_bc.get((b, c))
            if not r:
                cells.append("·")
                continue
            if is_infra(r):
                cells.append("🔧")
            elif r["status"] in ("SOLVED", "UNSOLVED", "TIMEOUT"):
                cells.append(f"{MARK.get(r['status'], '?')} {int(r['duration_s'])}s")
            else:
                cells.append(MARK.get(r["status"], "?"))
        out.append(f"| {b} | {lvl} | {cats} | " + " | ".join(cells) + " |")

    # fully-covered subset: every model produced a real (non-infra) agent run
    full = [b for b in benches if all((b, c) in by_bc and not is_infra(by_bc[(b, c)]) for c in combos)]
    if full:
        out.append("\n## Headline — fully-covered subset (apples-to-apples)\n")
        out.append(
            f"The **{len(full)} challenges every one of the four models actually ran** "
            f"({', '.join(full)}) — the only strictly comparable basis given the early stop:\n")
        out.append("| Model | Solved | Solve rate |")
        out.append("|---|---|---|")
        for c in combos:
            xs = [by_bc[(b, c)] for b in full]
            s = sum(1 for r in xs if r["solved"])
            out.append(f"| {COMBO_LABEL[c]} | {s}/{len(full)} | {100*s/len(full):.0f}% |")

    # aggregate per combo across ALL attempted (uneven denominators — see banner)
    out.append("\n## Aggregate by model (all attempted — uneven coverage)\n")
    out.append("| Model | Solved | Solve rate | Avg time (solved) | Claude $ | Codex tokens |")
    out.append("|---|---|---|---|---|---|")
    for c in combos:
        rs = [by_bc[(b, c)] for b in benches if (b, c) in by_bc]
        runnable = [r for r in rs if not is_infra(r)]
        solved = [r for r in runnable if r["solved"]]
        n = len(runnable)
        rate = f"{len(solved)}/{n} ({100*len(solved)/n:.0f}%)" if n else "n/a"
        avg_t = (sum(r["duration_s"] for r in solved) / len(solved)) if solved else 0
        cost = sum(r["cost_usd"] for r in rs)
        toks = sum(r["codex_tokens"] for r in rs)
        cost_s = f"${cost:.2f}" if cost else "—"
        toks_s = f"{toks:,}" if toks else "—"
        out.append(f"| {COMBO_LABEL[c]} | {len(solved)} | {rate} | "
                   f"{avg_t:.0f}s | {cost_s} | {toks_s} |")

    # by difficulty
    out.append("\n## Solve rate by difficulty\n")
    out.append("| Model | L2 (medium) | L3 (hard) |")
    out.append("|---|---|---|")
    for c in combos:
        rs = [by_bc[(b, c)] for b in benches if (b, c) in by_bc and not is_infra(by_bc[(b, c)])]
        l2 = [r for r in rs if r["level"] == "2"]
        l3 = [r for r in rs if r["level"] == "3"]

        def frac(xs: list[dict]) -> str:
            if not xs:
                return "—"
            s = sum(1 for r in xs if r["solved"])
            return f"{s}/{len(xs)} ({100*s/len(xs):.0f}%)"

        out.append(f"| {COMBO_LABEL[c]} | {frac(l2)} | {frac(l3)} |")

    if infra_bench:
        reasons = []
        for b in infra_bench:
            r = next((by_bc[(b, c)] for c in combos if (b, c) in by_bc), None)
            why = (r.get("error") or r["status"]) if r else "unknown"
            why = " ".join(why.split())  # collapse embedded newlines/whitespace
            if "manifest" in why:
                why = "mysql:5.7 — no arm64 manifest"
            elif "buster" in why or "deb.debian" in why:
                why = "EOL Debian-buster image — apt repo 404"
            reasons.append(f"`{b}`: {why[:80]}")
        out.append("\n## Excluded — infrastructure failures (not counted)\n")
        out.append(
            "These challenges never reached the agent (image build or container boot failed on "
            "this host) and are excluded from solve-rate denominators rather than scored as a "
            "model miss. On Apple-Silicon hosts the common causes are EOL Debian-buster/phantomjs "
            "images (apt 404) and `mysql:5.7` (no arm64 manifest):\n\n- " + "\n- ".join(reasons) + "\n")

    out.append("## Methodology\n")
    out.append(
        "- **Tool**: the autonomous `pentestgpt` CLI, CTF mode — a fixed 3-stage pipeline "
        "(recon → DFS exploit → walkthrough), each stage a fresh agent. The runtime is made "
        "pluggable via a new `--backend {claude,codex}` flag so all four models drive the "
        "*identical* pipeline and prompts.\n"
        "- **Targets**: each benchmark is built with `make build`, which bakes the ground-truth "
        "flag `FLAG{sha256(UPPERCASE-DIR)}` into the container. A fresh container is started per "
        "model run on a loopback-published port; the agent is pointed at `http://127.0.0.1:<port>`.\n"
        "- **Success**: the ground-truth flag string appears (case-insensitive) in the agent's "
        "captured stdout. This is identical for both runtimes (the agent must verbalize the flag; "
        "raw-mode does not echo tool-result bodies), keeping the comparison fair.\n"
        "- **Per-run timeout** and a fresh, isolated workspace per run; results are recorded "
        "per (challenge, model) and are resumable.\n")
    out.append("## Limitations\n")
    out.append(
        "- **Pilot sample** (not the full 59 medium/hard set) — chosen for category diversity and "
        "buildability; treat as indicative, not definitive.\n"
        "- **Cost is not directly comparable**: Claude bills per-token API ($ shown); Codex runs on "
        "a ChatGPT subscription (marginal $0), so token counts are shown instead.\n"
        "- **Codex reasoning effort** pinned to `medium` for tractable wall-clock; Claude exposes no "
        "equivalent knob, so timing is indicative, not a controlled latency benchmark.\n"
        "- **Single attempt per (challenge, model)** — the Dec-2025 baseline showed flaky timeouts "
        "recover on retry, so single-shot solve rates are a lower bound.\n"
        "- Scope/network reach is advisory (host shell); runs are bounded to loopback targets.\n")

    text = "\n".join(out) + "\n"
    REPORT_MD.write_text(text)
    print(text)


if __name__ == "__main__":
    render()
