from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_report():
    path = Path(__file__).resolve().parents[1] / "benchmark" / "pilot" / "report_best_of.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("report_best_of_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(
    *,
    attempt: int,
    status: str,
    solved: bool = False,
    variant: str = "pipeline",
    failure_class: str = "",
) -> dict:
    return {
        "benchmark_id": "XBEN-068-24",
        "combo": "claude-sonnet",
        "variant": variant,
        "attempt": attempt,
        "status": status,
        "solved": solved,
        "duration_s": 100 + attempt,
        "failure_class": failure_class,
    }


def test_best_of_uses_first_three_valid_attempts_and_excludes_infra() -> None:
    report = _load_report()
    rows = [
        _row(attempt=1, status="LIVENESS_ERROR", failure_class="infra"),
        _row(attempt=2, status="UNSOLVED"),
        _row(attempt=3, status="TIMEOUT"),
        _row(attempt=4, status="SOLVED", solved=True),
    ]

    cells = report.summarize_rows(rows, best_k=3)
    cell = cells[("XBEN-068-24", "claude-sonnet", "pipeline")]

    assert cell.complete is True
    assert cell.solved is True
    assert cell.attempts_to_solve == 4
    assert cell.timeout_count == 1
    assert [r["attempt"] for r in cell.used] == [2, 3, 4]
    assert len(cell.excluded) == 1


def test_best_of_keeps_framework_early_exit_out_of_valid_attempts() -> None:
    report = _load_report()
    rows = [
        _row(attempt=1, status="EARLY_EXIT", variant="framework", failure_class="early_exit"),
        _row(attempt=2, status="UNSOLVED", variant="framework"),
        _row(attempt=3, status="TIMEOUT", variant="framework"),
    ]

    cells = report.summarize_rows(rows, best_k=3)
    cell = cells[("XBEN-068-24", "claude-sonnet", "framework")]

    assert cell.complete is False
    assert cell.solved is False
    assert cell.status == "INCOMPLETE"
    assert [r["attempt"] for r in cell.used] == [2, 3]
    assert len(cell.excluded) == 1


def test_best_of_keeps_provider_network_errors_out_of_valid_attempts() -> None:
    report = _load_report()
    rows = [
        _row(
            attempt=1,
            status="PROVIDER_NETWORK_ERROR",
            variant="single",
            failure_class="provider_network",
        ),
        _row(attempt=2, status="UNSOLVED", variant="single"),
        _row(attempt=3, status="SOLVED", solved=True, variant="single"),
    ]

    cells = report.summarize_rows(rows, best_k=2)
    cell = cells[("XBEN-068-24", "claude-sonnet", "single")]

    assert cell.complete is True
    assert cell.solved is True
    assert [r["attempt"] for r in cell.used] == [2, 3]
    assert len(cell.excluded) == 1


def test_best_of_report_renders_head_to_head(tmp_path: Path) -> None:
    report = _load_report()
    output = tmp_path / "report.md"
    rows = [
        _row(attempt=1, status="SOLVED", solved=True, variant="pipeline"),
        _row(attempt=2, status="UNSOLVED", variant="pipeline"),
        _row(attempt=3, status="UNSOLVED", variant="pipeline"),
        _row(attempt=1, status="UNSOLVED", variant="framework"),
        _row(attempt=2, status="UNSOLVED", variant="framework"),
        _row(attempt=3, status="UNSOLVED", variant="framework"),
    ]

    text = report.render(rows, best_k=3, output=output)

    assert "Pipeline vs framework head-to-head" in text
    assert "| Claude Sonnet | 1 | 1 | 0 | -1 |" in text
    assert output.read_text() == text
