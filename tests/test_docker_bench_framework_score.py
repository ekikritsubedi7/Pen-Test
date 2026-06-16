from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "benchmark" / "pilot" / "run_docker_bench.py"
    spec = importlib.util.spec_from_file_location("run_docker_bench_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_framework_score_uses_only_accepted_ledger_findings(tmp_path: Path) -> None:
    runner = _load_runner()
    flag = "FLAG{accepted}"
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "ledger.json").write_text(
        json.dumps(
            {
                "accepted_finding_ids": ["good"],
                "findings": [
                    {
                        "id": "good",
                        "title": "flag recovered",
                        "affected_target": "http://target",
                        "description": "accepted flag finding",
                        "evidence_excerpt": flag,
                    },
                    {
                        "id": "bad",
                        "title": "unaccepted flag",
                        "affected_target": "http://target",
                        "description": "should not count",
                        "evidence_excerpt": "FLAG{rejected}",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    scored_text = runner._framework_report_text(tmp_path)
    assert flag in scored_text
    assert "FLAG{rejected}" not in scored_text

    scored = runner.score_framework("", runner.COMBOS[0], flag, True, scored_text)
    assert scored["solved"] is True
    assert scored["status"] == "SOLVED"
