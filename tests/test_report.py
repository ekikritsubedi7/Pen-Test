"""Tests for the accepted-only report renderer.

Core invariant: a finding appears in the report ONLY if the judge accepted it.
Rejected findings are documented as false-positive notes, never as findings.
"""

from __future__ import annotations

from pathlib import Path

from pentestgpt_agent.contracts import FindingProposal, JudgeVerdict
from pentestgpt_agent.ledger import (
    add_finding,
    new_run,
    record_completion,
    record_verdict,
)
from pentestgpt_agent.report import render_report, write_report
from pentestgpt_agent.scope import Scope


def _ledger(tmp_path: Path):  # type: ignore[no-untyped-def]
    return new_run("Assess the local web app", Scope.loopback(ports=(8000,)),
                   runs_root=tmp_path, run_id="r1")


def _finding(fid: str, title: str) -> FindingProposal:
    return FindingProposal(
        id=fid,
        title=title,
        affected_target="127.0.0.1:8000",
        severity="high",
        description="reflected user input",
        evidence_excerpt="MARKER-9F3A reflected verbatim",
        source_task_id="probe",
        remediation="escape output",
    )


def test_report_with_no_accepted_findings_states_none(tmp_path: Path) -> None:
    led = _ledger(tmp_path)
    add_finding(led, _finding("probe-f0", "Bogus XSS"))
    record_verdict(led, "probe-f0", JudgeVerdict(decision="reject", rationale="not reproducible"))

    report = render_report(led)
    assert "No findings were accepted." in report
    # the rejected title is documented as a note, not presented as a finding section
    assert "not reproducible" in report


def test_report_lists_accepted_finding_with_evidence(tmp_path: Path) -> None:
    led = _ledger(tmp_path)
    add_finding(led, _finding("probe-f0", "Reflected XSS"))
    record_verdict(led, "probe-f0", JudgeVerdict(decision="accept", rationale="reproduced"))

    report = render_report(led)
    assert "Reflected XSS" in report
    assert "127.0.0.1:8000" in report
    assert "MARKER-9F3A reflected verbatim" in report
    assert "high" in report.lower()
    assert "No findings were accepted." not in report


def test_report_includes_scope_and_advisory_disclaimer(tmp_path: Path) -> None:
    report = render_report(_ledger(tmp_path))
    assert "127.0.0.1" in report
    assert "advisory" in report.lower()  # scope-is-not-a-guardrail disclaimer


def test_report_shows_completion_verdict(tmp_path: Path) -> None:
    led = _ledger(tmp_path)
    record_completion(led, JudgeVerdict(decision="accept", rationale="assessment complete"))
    report = render_report(led)
    assert "assessment complete" in report


def test_write_report_creates_file_and_returns_path(tmp_path: Path) -> None:
    led = _ledger(tmp_path)
    add_finding(led, _finding("probe-f0", "Reflected XSS"))
    record_verdict(led, "probe-f0", JudgeVerdict(decision="accept", rationale="reproduced"))

    path = write_report(led)
    assert path == str(tmp_path / "r1" / "report.md")
    assert "Reflected XSS" in Path(path).read_text(encoding="utf-8")
