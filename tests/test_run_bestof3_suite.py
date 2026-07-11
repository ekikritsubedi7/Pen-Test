from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_suite():
    path = Path(__file__).resolve().parents[1] / "benchmark" / "pilot" / "run_bestof3_suite.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("run_bestof3_suite_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_framework_runner_command_uses_bestof3_defaults() -> None:
    suite = _load_suite()

    cmd = suite._runner_cmd(
        variant="framework",
        image="pentestgpt:latest",
        source_root="../..",
        benchmarks="XBEN-068-24,XBEN-080-24",
        timeout=2400,
        concurrency=2,
        max_codex=1,
        attempt=1,
        attempts=3,
        out=Path("docker_bof3_test_framework.jsonl"),
        framework_executor_concurrency=2,
    )

    assert cmd[:4] == ["uv", "run", "python", "run_docker_bench.py"]
    assert "--variant" in cmd
    assert cmd[cmd.index("--variant") + 1] == "framework"
    assert cmd[cmd.index("--attempts") + 1] == "3"
    assert cmd[cmd.index("--max-codex") + 1] == "1"
    assert cmd[cmd.index("--framework-executor-concurrency") + 1] == "2"
    assert cmd[cmd.index("--out") + 1] == "docker_bof3_test_framework.jsonl"


def test_canary_validation_accepts_valid_retry_after_excluded_row(tmp_path: Path) -> None:
    suite = _load_suite()
    path = tmp_path / "canary.jsonl"
    rows = [
        {
            "benchmark_id": "XBEN-068-24",
            "combo": "claude-sonnet",
            "variant": "framework",
            "attempt": 1,
            "status": "LIVENESS_ERROR",
            "solved": False,
            "duration_s": 0,
            "failure_class": "infra",
        },
        {
            "benchmark_id": "XBEN-068-24",
            "combo": "claude-sonnet",
            "variant": "framework",
            "attempt": 1,
            "status": "UNSOLVED",
            "solved": False,
            "duration_s": 90,
            "failure_class": "",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    suite._validate_canary(
        path,
        benchmarks="XBEN-068-24",
        combos="claude-sonnet",
        variant="framework",
    )


def test_canary_validation_rejects_missing_valid_attempt(tmp_path: Path) -> None:
    suite = _load_suite()
    path = tmp_path / "canary.jsonl"
    path.write_text(
        json.dumps(
            {
                "benchmark_id": "XBEN-068-24",
                "combo": "claude-sonnet",
                "variant": "framework",
                "attempt": 1,
                "status": "AUTH_ERROR",
                "solved": False,
                "duration_s": 0,
                "failure_class": "auth",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="no valid attempt"):
        suite._validate_canary(
            path,
            benchmarks="XBEN-068-24",
            combos="claude-sonnet",
            variant="framework",
        )
