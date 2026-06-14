"""Tests for structured scope enforcement.

Scope is enforced BEFORE an executor is dispatched and on every finding. Note
this is an *advisory* control in v1 (a WORKSPACE_WRITE executor has a real
shell); the real guardrail is a future network layer. These tests pin the
orchestrator-level gate.
"""

from __future__ import annotations

import pytest

from pentestgpt_agent.contracts import FindingProposal, TaskCard
from pentestgpt_agent.scope import (
    Scope,
    check_card,
    check_finding,
    detect_candidate_signals,
    host_of,
    is_in_scope,
    port_of,
    scope_from_target,
)


@pytest.mark.parametrize(
    ("target", "host", "port"),
    [
        ("http://127.0.0.1:8000/path?q=1", "127.0.0.1", 8000),
        ("127.0.0.1:8000", "127.0.0.1", 8000),
        ("127.0.0.1", "127.0.0.1", None),
        ("localhost", "localhost", None),
        ("https://example.com", "example.com", None),
        ("[::1]:8080", "::1", 8080),
    ],
)
def test_host_and_port_parsing(target: str, host: str, port: int | None) -> None:
    assert host_of(target) == host
    assert port_of(target) == port


def test_loopback_scope_allows_localhost_rejects_others() -> None:
    scope = Scope.loopback()
    assert is_in_scope(scope, "http://127.0.0.1:8000") is True
    assert is_in_scope(scope, "localhost") is True
    assert is_in_scope(scope, "http://10.0.0.5") is False
    assert is_in_scope(scope, "http://example.com") is False


def test_none_target_is_in_scope_so_planning_is_allowed() -> None:
    assert is_in_scope(Scope.loopback(), None) is True


def test_allowed_ports_are_enforced_when_set() -> None:
    scope = Scope.loopback(ports=(8000,))
    assert is_in_scope(scope, "127.0.0.1:8000") is True
    assert is_in_scope(scope, "127.0.0.1:9999") is False
    assert is_in_scope(scope, "127.0.0.1") is True  # unspecified port still host-gated


def test_check_card_passes_no_target_and_in_scope_target() -> None:
    scope = Scope.loopback()
    assert check_card(scope, TaskCard(id="t", instruction="plan")) is None
    assert check_card(scope, TaskCard(id="t", instruction="x", affected_target="127.0.0.1:8000")) is None


def test_check_card_rejects_out_of_scope_target() -> None:
    scope = Scope.loopback()
    reason = check_card(scope, TaskCard(id="t", instruction="x", affected_target="10.0.0.5"))
    assert reason is not None
    assert "10.0.0.5" in reason


def _finding(target: str) -> FindingProposal:
    return FindingProposal(
        id="f0",
        title="t",
        affected_target=target,
        severity="medium",
        description="d",
        evidence_excerpt="e",
        source_task_id="t",
    )


def test_check_finding_requires_in_scope_target() -> None:
    scope = Scope.loopback()
    assert check_finding(scope, _finding("127.0.0.1")) is None
    assert check_finding(scope, _finding("10.0.0.5")) is not None
    assert check_finding(scope, _finding("")) is not None  # findings must name a target


def test_scope_round_trips_through_dict() -> None:
    scope = Scope.loopback(ports=(8000, 8443))
    restored = Scope.from_dict(scope.to_dict())
    assert restored == scope


def test_scope_from_target_loopback_url_includes_aliases() -> None:
    scope = scope_from_target("http://127.0.0.1:8000")
    assert is_in_scope(scope, "http://127.0.0.1:8000")
    assert is_in_scope(scope, "localhost:8000")  # loopback aliases grouped
    assert not is_in_scope(scope, "http://10.0.0.5:8000")
    assert scope.allowed_ports == (8000,)


def test_scope_from_target_external_host_with_extra_hosts() -> None:
    scope = scope_from_target("https://192.168.1.10", extra_hosts=("192.168.1.11",))
    assert is_in_scope(scope, "192.168.1.10")
    assert is_in_scope(scope, "192.168.1.11")
    assert not is_in_scope(scope, "127.0.0.1")


def test_detect_candidate_signals_finds_flags_and_hashes_deduped() -> None:
    text = "found flag{abc} and again flag{abc} plus d41d8cd98f00b204e9800998ecf8427e"
    signals = detect_candidate_signals(text)
    assert "flag{abc}" in signals
    assert "d41d8cd98f00b204e9800998ecf8427e" in signals
    assert len(signals) == len(set(signals))  # deduped
