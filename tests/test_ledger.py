"""Tests for the single-writer durable ledger.

Reload is snapshot-based (``ledger.json``), never a replay of ``events.jsonl`` —
proven by corrupting the event log and reloading anyway.
"""

from __future__ import annotations

from pathlib import Path

from pentestgpt_agent.contracts import (
    EvidenceBundle,
    FindingProposal,
    JudgeVerdict,
    NodeStatus,
    TaskCard,
)
from pentestgpt_agent.ledger import (
    add_cards,
    add_finding,
    has_open_work,
    load,
    mark_running,
    new_run,
    ready_ids,
    recompute_ready,
    record_completion,
    record_evidence,
    record_failure,
    record_verdict,
    reject_card,
    running_ids,
    unsatisfiable_blocked,
)
from pentestgpt_agent.scope import Scope


def _scope() -> Scope:
    return Scope.loopback(ports=(8000,))


def _finding(fid: str, target: str = "127.0.0.1") -> FindingProposal:
    return FindingProposal(
        id=fid,
        title="t",
        affected_target=target,
        severity="medium",
        description="d",
        evidence_excerpt="e",
        source_task_id="a",
    )


def test_new_run_creates_run_directory(tmp_path: Path) -> None:
    led = new_run("goal", _scope(), runs_root=tmp_path, run_id="r1")
    rd = tmp_path / "r1"
    assert (rd / "scope.json").is_file()
    assert (rd / "ledger.json").is_file()
    assert (rd / "events.jsonl").is_file()
    assert (rd / "artifacts").is_dir()
    assert led.run_id == "r1"


def test_add_cards_sets_ready_blocked_and_skips_duplicates(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    added = add_cards(
        led,
        [
            TaskCard(id="a", instruction="x"),
            TaskCard(id="b", instruction="y", depends_on=("a",)),
        ],
    )
    assert set(added) == {"a", "b"}
    assert led.nodes["a"].status is NodeStatus.READY
    assert led.nodes["b"].status is NodeStatus.BLOCKED

    again = add_cards(led, [TaskCard(id="a", instruction="OVERWRITE")])
    assert again == []
    assert led.nodes["a"].card.instruction == "x"  # original preserved


def test_record_evidence_promotes_dependent_to_ready(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    add_cards(led, [TaskCard(id="a", instruction="x"), TaskCard(id="b", instruction="y", depends_on=("a",))])
    mark_running(led, "a")
    record_evidence(led, "a", EvidenceBundle(task_id="a"))
    assert led.nodes["a"].status is NodeStatus.DONE
    assert led.nodes["b"].status is NodeStatus.READY
    assert "b" in ready_ids(led)


def test_mark_running_counts_dispatch_and_attempts(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    add_cards(led, [TaskCard(id="a", instruction="x")])
    mark_running(led, "a")
    assert led.nodes["a"].status is NodeStatus.RUNNING
    assert led.nodes["a"].attempts == 1
    assert led.dispatch_count == 1
    assert running_ids(led) == ["a"]


def test_record_failure_blocks_dependents_and_ends_open_work(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    add_cards(led, [TaskCard(id="a", instruction="x"), TaskCard(id="b", instruction="y", depends_on=("a",))])
    mark_running(led, "a")
    record_failure(led, "a", "boom")
    assert led.nodes["a"].status is NodeStatus.FAILED
    assert led.nodes["a"].failure_reason == "boom"
    assert "b" in unsatisfiable_blocked(led)
    assert has_open_work(led) is False


def test_unsatisfiable_dependency_is_transitive(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    add_cards(
        led,
        [
            TaskCard(id="a", instruction="x", depends_on=("missing",)),
            TaskCard(id="b", instruction="y", depends_on=("a",)),
        ],
    )
    assert set(unsatisfiable_blocked(led)) == {"a", "b"}
    assert has_open_work(led) is False


def test_findings_accept_and_reject_routing(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    add_finding(led, _finding("a-f0"))
    add_finding(led, _finding("a-f1"))
    record_verdict(led, "a-f0", JudgeVerdict(decision="accept", rationale="real"))
    record_verdict(led, "a-f1", JudgeVerdict(decision="reject", rationale="false positive"))
    assert led.accepted_finding_ids == {"a-f0"}
    assert ("a-f1", "false positive") in led.rejected_findings
    assert "a-f1" not in led.accepted_finding_ids


def test_record_completion_sets_verdict(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    record_completion(led, JudgeVerdict(decision="accept", rationale="done"))
    assert led.completion_verdict is not None
    assert led.completion_verdict.decision == "accept"


def test_reject_card_records_rejected_node(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    reject_card(led, TaskCard(id="bad", instruction="x", affected_target="10.0.0.5"), "out of scope")
    assert led.nodes["bad"].status is NodeStatus.REJECTED
    assert led.nodes["bad"].failure_reason is not None
    assert "out of scope" in led.nodes["bad"].failure_reason


def test_persist_and_reload_from_snapshot(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    add_cards(led, [TaskCard(id="a", instruction="x", affected_target="127.0.0.1:8000")])
    mark_running(led, "a")
    record_evidence(led, "a", EvidenceBundle(task_id="a", observations=("server up",)))
    add_finding(led, _finding("a-f0"))
    record_verdict(led, "a-f0", JudgeVerdict(decision="accept", rationale="real"))

    reloaded = load("r1", runs_root=tmp_path)
    assert reloaded.run_id == "r1"
    assert reloaded.nodes["a"].status is NodeStatus.DONE
    assert reloaded.nodes["a"].evidence is not None
    assert reloaded.nodes["a"].evidence.observations == ("server up",)
    assert reloaded.accepted_finding_ids == {"a-f0"}
    assert reloaded.scope == _scope()
    assert (tmp_path / "r1" / "events.jsonl").read_text(encoding="utf-8").strip()


def test_reload_ignores_corrupt_event_log(tmp_path: Path) -> None:
    led = new_run("g", _scope(), runs_root=tmp_path, run_id="r1")
    add_cards(led, [TaskCard(id="a", instruction="x")])
    recompute_ready(led)
    (tmp_path / "r1" / "events.jsonl").write_text("NOT JSON\n{bad", encoding="utf-8")
    reloaded = load("r1", runs_root=tmp_path)  # must reconstruct from snapshot only
    assert "a" in reloaded.nodes
