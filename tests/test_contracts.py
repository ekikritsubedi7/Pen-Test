"""Tests for the framework's typed contracts, schemas, and defensive parsers.

The parsers are the chokepoint that converts a backend's silent
``structured_output=None`` (Codex on JSON-parse failure) or any malformed dict
into a typed, recordable ``ContractError`` — never a half-built object.
"""

from __future__ import annotations

from typing import Any

import pytest

from pentestgpt_agent.contracts import (
    EXECUTOR_SCHEMA,
    INSTRUCTOR_SCHEMA,
    JUDGE_SCHEMA,
    CandidateFinding,
    CommandRecord,
    ContractError,
    EvidenceBundle,
    FindingProposal,
    JudgeVerdict,
    NodeStatus,
    TaskCard,
    finding_from_candidate,
    parse_evidence,
    parse_instructor,
    parse_verdict,
)


def _assert_codex_strict(schema: dict[str, Any]) -> None:
    """Every object node must forbid extra props and require all its properties."""
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        assert schema.get("additionalProperties") is False, schema
        assert set(schema.get("required", [])) == set(props), schema
        for sub in props.values():
            _assert_codex_strict(sub)
    if schema.get("type") == "array":
        _assert_codex_strict(schema["items"])


# --- enums / dataclass defaults -------------------------------------------------


def test_node_status_has_six_lifecycle_states() -> None:
    assert {s.value for s in NodeStatus} == {
        "blocked",
        "ready",
        "running",
        "done",
        "failed",
        "rejected",
    }


def test_task_card_defaults_are_isolation_safe() -> None:
    card = TaskCard(id="t1", instruction="probe")
    assert card.depends_on == ()
    assert card.affected_target is None
    assert card.origin == "instructor"


def test_evidence_bundle_defaults_are_empty_tuples() -> None:
    bundle = EvidenceBundle(task_id="t1")
    assert bundle.commands == ()
    assert bundle.candidate_findings == ()
    assert bundle.needs_followup is False


# --- schemas are Codex-strict ---------------------------------------------------


@pytest.mark.parametrize("schema", [INSTRUCTOR_SCHEMA, EXECUTOR_SCHEMA, JUDGE_SCHEMA])
def test_schemas_are_codex_strict(schema: dict[str, Any]) -> None:
    _assert_codex_strict(schema)


# --- parse_instructor -----------------------------------------------------------


def test_parse_instructor_rejects_non_dict() -> None:
    with pytest.raises(ContractError):
        parse_instructor(None)


def test_parse_instructor_parses_tasks_and_coerces_depends_on_to_tuple() -> None:
    raw = {
        "propose_completion": False,
        "completion_summary": "",
        "tasks": [
            {
                "id": "recon",
                "instruction": "enumerate",
                "context": None,
                "executor": None,
                "max_turns": None,
                "depends_on": [],
                "affected_target": "127.0.0.1",
            },
            {
                "id": "exploit",
                "instruction": "attack",
                "context": "use recon output",
                "executor": None,
                "max_turns": 5,
                "depends_on": ["recon"],
                "affected_target": "127.0.0.1",
            },
        ],
    }
    propose, summary, cards = parse_instructor(raw)
    assert propose is False
    assert summary == ""
    assert [c.id for c in cards] == ["recon", "exploit"]
    assert cards[1].depends_on == ("recon",)
    assert isinstance(cards[1].depends_on, tuple)
    assert cards[1].max_turns == 5


def test_parse_instructor_requires_bool_completion_flag() -> None:
    with pytest.raises(ContractError):
        parse_instructor({"propose_completion": "yes", "completion_summary": "", "tasks": []})


def test_parse_instructor_rejects_blank_task_id() -> None:
    raw = {
        "propose_completion": False,
        "completion_summary": "",
        "tasks": [{"id": "  ", "instruction": "x", "context": None, "executor": None,
                   "max_turns": None, "depends_on": [], "affected_target": None}],
    }
    with pytest.raises(ContractError):
        parse_instructor(raw)


# --- parse_evidence -------------------------------------------------------------


def test_parse_evidence_rejects_none_structured_output() -> None:
    with pytest.raises(ContractError):
        parse_evidence(None, task_id="t1")


def test_parse_evidence_builds_typed_tuples_and_forces_task_id() -> None:
    raw = {
        "task_id": "WRONG-echoed-by-model",
        "commands": [{"command": "curl localhost", "exit_code": 0, "output_excerpt": "200 OK"}],
        "observations": ["server responds"],
        "artifacts": [],
        "errors": [],
        "candidate_findings": [
            {
                "title": "Reflected input",
                "affected_target": "127.0.0.1",
                "severity": "medium",
                "summary": "q is reflected unescaped",
                "evidence_excerpt": "<script>",
                "confidence": "high",
            }
        ],
        "needs_followup": False,
        "followup_reason": None,
    }
    bundle = parse_evidence(raw, task_id="t1")
    assert bundle.task_id == "t1"  # authoritative param, not the model's echo
    assert isinstance(bundle.commands[0], CommandRecord)
    assert bundle.commands[0].exit_code == 0
    assert isinstance(bundle.candidate_findings[0], CandidateFinding)
    assert bundle.candidate_findings[0].confidence == "high"


# --- parse_verdict --------------------------------------------------------------


def test_parse_verdict_rejects_non_dict() -> None:
    with pytest.raises(ContractError):
        parse_verdict(None)


def test_parse_verdict_rejects_unknown_decision() -> None:
    with pytest.raises(ContractError):
        parse_verdict({"decision": "maybe", "rationale": "", "verifier_instruction": None,
                       "verifier_target": None})


def test_parse_verdict_accepts_known_decisions() -> None:
    v = parse_verdict({"decision": "needs_more", "rationale": "reproduce it",
                       "verifier_instruction": "rerun curl", "verifier_target": "127.0.0.1"})
    assert isinstance(v, JudgeVerdict)
    assert v.decision == "needs_more"
    assert v.verifier_instruction == "rerun curl"


# --- finding promotion ----------------------------------------------------------


def test_finding_from_candidate_carries_evidence_and_ids() -> None:
    cand = CandidateFinding(
        title="Reflected input",
        affected_target="127.0.0.1",
        severity="medium",
        summary="q reflected",
        evidence_excerpt="<script>",
        confidence="high",
    )
    fp = finding_from_candidate(cand, finding_id="t1-f0", source_task_id="t1")
    assert isinstance(fp, FindingProposal)
    assert fp.id == "t1-f0"
    assert fp.source_task_id == "t1"
    assert fp.title == "Reflected input"
    assert fp.evidence_excerpt == "<script>"
