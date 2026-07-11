from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

PILOT_DIR = Path(__file__).resolve().parents[1] / "benchmark" / "pilot"
REGISTRY = PILOT_DIR / "benchmark_sets.json"


def _load():
    path = PILOT_DIR / "bench_set.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("bench_set_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bs = _load()


# --- registry + enabled-id computation -------------------------------------
def test_registry_loads_hard_open_with_ten_all_enabled() -> None:
    reg = bs.load_registry(REGISTRY)
    hard = bs.get_set(reg, "hard-open")
    chs = bs.challenges(hard)
    assert len(chs) == 10
    assert bs.enabled_ids(hard) == [c["id"] for c in chs]  # all enabled, in order
    levels = sorted(c["level"] for c in chs)
    assert levels.count(3) == 8 and levels.count(2) == 2


def test_get_set_unknown_raises() -> None:
    with pytest.raises(SystemExit):
        bs.get_set(bs.load_registry(REGISTRY), "does-not-exist")


# --- toggling --------------------------------------------------------------
def test_set_enabled_flips_reports_changes_and_is_idempotent() -> None:
    reg = bs.load_registry(REGISTRY)
    hard = bs.get_set(reg, "hard-open")

    changed, unknown = bs.set_enabled(hard, ["XBEN-057-24", "XBEN-101-24"], False)
    assert set(changed) == {"XBEN-057-24", "XBEN-101-24"} and unknown == []
    assert "XBEN-057-24" not in bs.enabled_ids(hard)

    # disabling again is a no-op
    changed2, _ = bs.set_enabled(hard, ["XBEN-057-24"], False)
    assert changed2 == []


def test_set_enabled_all_and_unknown() -> None:
    hard = bs.get_set(bs.load_registry(REGISTRY), "hard-open")
    bs.set_enabled(hard, ["all"], False)
    assert bs.enabled_ids(hard) == []
    changed, _ = bs.set_enabled(hard, ["all"], True)
    assert len(changed) == 10

    _, unknown = bs.set_enabled(hard, ["XBEN-999-99"], False)
    assert unknown == ["XBEN-999-99"]


def test_disable_enable_via_cli_persists(tmp_path) -> None:
    reg_copy = tmp_path / "sets.json"
    shutil.copy(REGISTRY, reg_copy)

    bs.main(["disable", "XBEN-057-24", "XBEN-101-24", "--set", "hard-open", "--sets-file", str(reg_copy)])
    hard = bs.get_set(json.loads(reg_copy.read_text()), "hard-open")
    assert bs.enabled_ids(hard) == [
        "XBEN-010-24", "XBEN-018-24", "XBEN-066-24", "XBEN-087-24",
        "XBEN-088-24", "XBEN-093-24", "XBEN-001-24", "XBEN-080-24",
    ]

    bs.main(["enable", "XBEN-057-24", "--set", "hard-open", "--sets-file", str(reg_copy)])
    hard = bs.get_set(json.loads(reg_copy.read_text()), "hard-open")
    assert "XBEN-057-24" in bs.enabled_ids(hard)


# --- parallelism -----------------------------------------------------------
def test_suggest_and_resolve_concurrency() -> None:
    assert bs.suggest_concurrency(10) == 2  # capped at the conservative base
    assert bs.suggest_concurrency(1) == 1
    assert bs.resolve_concurrency("auto", 10) == 2
    assert bs.resolve_concurrency("5", 10) == 5  # explicit override wins
    with pytest.raises(SystemExit):
        bs.resolve_concurrency("0", 10)
    with pytest.raises(SystemExit):
        bs.resolve_concurrency("nan", 10)


def test_variants_for() -> None:
    assert bs.variants_for("both") == ["single", "framework"]
    assert bs.variants_for("framework") == ["framework"]


# --- run planning (no Docker) ----------------------------------------------
def _run_args(tmp_path, *extra: str):
    # a real-but-empty root so resolve_xben_root succeeds deterministically
    root = tmp_path / "xben_root"
    root.mkdir()
    argv = [
        "run", "--set", "hard-open", "--sets-file", str(REGISTRY),
        "--xben-root", str(root), *extra,
    ]
    return bs.build_parser().parse_args(argv), root


def test_plan_run_framework_command(tmp_path) -> None:
    args, _ = _run_args(tmp_path, "--variant", "framework", "--concurrency", "auto")
    plan = bs.plan_run(args)
    assert len(plan["commands"]) == 1
    cmd = plan["commands"][0]
    assert "--variant" in cmd and cmd[cmd.index("--variant") + 1] == "framework"
    benchmarks = cmd[cmd.index("--benchmarks") + 1]
    assert benchmarks == ",".join(plan["enabled_ids"])
    assert cmd[cmd.index("--concurrency") + 1] == "2"  # auto over 10 enabled
    assert "--framework-executor-concurrency" in cmd
    assert cmd[cmd.index("--out") + 1] == "docker_framework_hard-open.jsonl"


def test_plan_run_both_emits_two_commands(tmp_path) -> None:
    args, _ = _run_args(tmp_path, "--variant", "both", "--concurrency", "4")
    plan = bs.plan_run(args)
    variants = [c[c.index("--variant") + 1] for c in plan["commands"]]
    assert variants == ["single", "framework"]
    # single leg carries no framework-only flag; framework leg does
    assert "--framework-executor-concurrency" not in plan["commands"][0]
    assert "--framework-executor-concurrency" in plan["commands"][1]
    assert all(c[c.index("--concurrency") + 1] == "4" for c in plan["commands"])


def test_plan_run_unknown_combo_rejected(tmp_path) -> None:
    args, _ = _run_args(tmp_path, "--combos", "not-a-combo")
    with pytest.raises(SystemExit):
        bs.plan_run(args)


# --- fixture preflight -----------------------------------------------------
def test_missing_dirs(tmp_path) -> None:
    root = tmp_path / "root"
    (root / "XBEN-010-24").mkdir(parents=True)
    assert bs.missing_dirs(root, ["XBEN-010-24", "XBEN-018-24"]) == ["XBEN-018-24"]


def test_run_errors_when_fixture_dirs_missing(tmp_path) -> None:
    args, _ = _run_args(tmp_path, "--concurrency", "1")  # empty root -> all 10 missing
    with pytest.raises(SystemExit):
        bs.cmd_run(args)  # guard fires before any subprocess


def test_run_dry_run_with_missing_dirs_is_nonfatal(tmp_path, capsys) -> None:
    args, _ = _run_args(tmp_path, "--concurrency", "1", "--dry-run")
    assert bs.cmd_run(args) == 0
    out = capsys.readouterr().out
    assert "WARNING" in out and "run_docker_bench.py" in out
