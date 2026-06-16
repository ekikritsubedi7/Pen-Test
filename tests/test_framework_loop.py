"""Tests for the ledger-centered orchestrator, driven by fake agents.

These assert the framework's *semantics* with zero real backends: DAG scheduling,
the mandatory judge gate on findings and completion, bounded reproduction,
scope refusal before dispatch, and clean termination on every edge case.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pentestgpt_agent.contracts import NodeStatus
from pentestgpt_agent.framework_loop import FrameworkConfig, FrameworkLoop
from pentestgpt_agent.ledger import load
from pentestgpt_agent.scope import Scope
from unified_agent import Task, UnifiedResult, UnifiedUsage

# --- fakes & builders -----------------------------------------------------------


def make_result(structured_output: Any) -> UnifiedResult:
    return UnifiedResult(
        backend="fake",
        success=True,
        text="" if structured_output is None else "see structured output",
        structured_output=structured_output,
        usage=UnifiedUsage(),
        cost_usd=None,
        session_id=None,
        duration_ms=None,
        tool_calls=[],
        file_changes=[],
        events=[],
        error=None,
    )


class FakeAgent:
    def __init__(self, responder: Any, *, delay: float = 0.0) -> None:
        self.responder = responder
        self.delay = delay
        self.calls: list[SimpleNamespace] = []

    async def run(
        self,
        task: Task | str,
        *,
        output_schema: dict[str, Any] | None = None,
        resume: str | None = None,
        max_turns: int | None = None,
    ) -> UnifiedResult:
        idx = len(self.calls)
        self.calls.append(SimpleNamespace(task=task, output_schema=output_schema, max_turns=max_turns))
        if self.delay:
            await asyncio.sleep(self.delay)
        out = self.responder(task, idx)
        if isinstance(out, BaseException):
            raise out
        return make_result(out)


def seq(items: list[Any]) -> Any:
    return lambda task, idx: items[idx] if idx < len(items) else items[-1]


def always(item: Any) -> Any:
    return lambda task, idx: item


def by_text(rules: list[tuple[str, Any]], default: Any = None) -> Any:
    def responder(task: Task | str, idx: int) -> Any:
        text = getattr(task, "instruction", None) or str(task)
        for needle, value in rules:
            if needle in text:
                return value
        return default

    return responder


def tcard(
    cid: str,
    instruction: str,
    *,
    context: str | None = None,
    executor: str | None = None,
    depends_on: tuple[str, ...] = (),
    affected_target: str | None = "127.0.0.1:8000",
) -> dict[str, Any]:
    return {
        "id": cid,
        "instruction": instruction,
        "context": context,
        "executor": executor,
        "max_turns": None,
        "depends_on": list(depends_on),
        "affected_target": affected_target,
    }


def instr(*, propose: bool = False, summary: str = "", tasks: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    return {"propose_completion": propose, "completion_summary": summary, "tasks": list(tasks)}


def cand(title: str = "Reflected XSS", target: str = "127.0.0.1:8000", **kw: Any) -> dict[str, Any]:
    base = {
        "title": title,
        "affected_target": target,
        "severity": "high",
        "summary": "input reflected",
        "evidence_excerpt": "MARKER",
        "confidence": "high",
    }
    base.update(kw)
    return base


def evidence(*, findings: tuple[dict[str, Any], ...] = (), observations: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "task_id": "x",
        "commands": [],
        "observations": list(observations),
        "artifacts": [],
        "errors": [],
        "candidate_findings": list(findings),
        "needs_followup": False,
        "followup_reason": None,
    }


def verdict(decision: str, *, vinstr: str | None = None, vtarget: str | None = None) -> dict[str, Any]:
    return {
        "decision": decision,
        "rationale": f"{decision} rationale",
        "verifier_instruction": vinstr,
        "verifier_target": vtarget,
    }


def build(
    instructor: FakeAgent,
    executor: FakeAgent,
    judge: FakeAgent,
    *,
    runs_root: Path,
    scope: Scope | None = None,
    config: FrameworkConfig | None = None,
) -> FrameworkLoop:
    return FrameworkLoop(
        instructor=instructor,
        executors={"exec": executor},
        judge=judge,
        scope=scope or Scope.loopback(ports=(8000,)),
        config=config or FrameworkConfig(max_rounds=4, max_total_dispatches=20),
        runs_root=runs_root,
    )


# --- tests ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_receives_only_card_context_not_the_goal(tmp_path: Path) -> None:
    secret = "GLOBAL-GOAL-SECRET-NOT-FOR-EXECUTOR"
    instructor = FakeAgent(seq([instr(tasks=(tcard("p", "probe endpoint", context="only local ctx"),)), instr(propose=True)]))
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("accept")))

    await build(instructor, executor, judge, runs_root=tmp_path).run(secret)

    task = executor.calls[0].task
    assert isinstance(task, Task)
    assert task.instruction == "probe endpoint"
    assert task.context == "only local ctx"
    assert secret not in task.instruction
    assert secret not in (task.context or "")


@pytest.mark.asyncio
async def test_independent_leaves_run_concurrently(tmp_path: Path) -> None:
    instructor = FakeAgent(seq([instr(tasks=(tcard("a", "probe a"), tcard("b", "probe b"))), instr(propose=True)]))
    executor = FakeAgent(always(evidence()), delay=0.2)
    judge = FakeAgent(always(verdict("accept")))

    started = time.monotonic()
    await build(instructor, executor, judge, runs_root=tmp_path).run("goal")
    elapsed = time.monotonic() - started

    assert len(executor.calls) == 2
    assert elapsed < 0.35  # concurrent, not 0.4s serial


@pytest.mark.asyncio
async def test_dependent_task_waits_for_dependency(tmp_path: Path) -> None:
    instructor = FakeAgent(
        seq([instr(tasks=(tcard("recon", "probe recon"), tcard("exploit", "probe exploit", depends_on=("recon",)))), instr(propose=True)])
    )
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("accept")))

    await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    order = [c.task.instruction for c in executor.calls]
    assert order == ["probe recon", "probe exploit"]  # recon strictly before exploit


@pytest.mark.asyncio
async def test_unknown_executor_label_falls_back_to_default(tmp_path: Path) -> None:
    instructor = FakeAgent(
        seq([instr(tasks=(tcard("p", "probe endpoint", executor="web-recon"),)), instr(propose=True)])
    )
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("accept")))

    loop = build(instructor, executor, judge, runs_root=tmp_path)
    await loop.run("goal")

    assert [c.task.instruction for c in executor.calls] == ["probe endpoint"]
    assert loop.ledger is not None
    assert any("unknown executor 'web-recon'" in note for note in loop.ledger.notes)


@pytest.mark.asyncio
async def test_instructor_cannot_complete_without_judge_acceptance(tmp_path: Path) -> None:
    instructor = FakeAgent(always(instr(propose=True, summary="i say done")))
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("reject")))

    result = await build(
        instructor, executor, judge, runs_root=tmp_path, config=FrameworkConfig(max_rounds=2)
    ).run("goal")

    assert result.completed is False
    assert judge.calls  # the completion gate was actually consulted


@pytest.mark.asyncio
async def test_judge_acceptance_completes_the_run(tmp_path: Path) -> None:
    instructor = FakeAgent(always(instr(propose=True, summary="done")))
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("accept")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    assert result.completed is True
    assert result.reason == "completed"


@pytest.mark.asyncio
async def test_rejected_finding_absent_from_report(tmp_path: Path) -> None:
    instructor = FakeAgent(seq([instr(tasks=(tcard("p", "probe"),)), instr(propose=True)]))
    executor = FakeAgent(by_text([("probe", evidence(findings=(cand(title="Bogus"),)))], default=evidence()))
    judge = FakeAgent(by_text([("COMPLETION", verdict("accept"))], default=verdict("reject")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    report = Path(result.report_path).read_text(encoding="utf-8")
    assert "No findings were accepted." in report
    assert not result.accepted_findings


@pytest.mark.asyncio
async def test_needs_more_spawns_verifier_then_accepts(tmp_path: Path) -> None:
    instructor = FakeAgent(seq([instr(tasks=(tcard("p", "probe"),)), instr(propose=True)]))
    executor = FakeAgent(by_text([("reproduce", evidence()), ("probe", evidence(findings=(cand(),)))], default=evidence()))
    judge = FakeAgent(seq([verdict("needs_more", vinstr="reproduce it", vtarget="127.0.0.1:8000"), verdict("accept"), verdict("accept")]))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    led = load(result.run_id, runs_root=tmp_path)
    verifier_nodes = [n for n in led.nodes.values() if n.card.origin == "verifier"]
    assert verifier_nodes  # a bounded verifier task was created
    assert "p-f0" in led.accepted_finding_ids  # finding accepted only after reproduction
    assert any("reproduce" in c.task.instruction for c in executor.calls)


@pytest.mark.asyncio
async def test_out_of_scope_card_rejected_before_dispatch(tmp_path: Path) -> None:
    instructor = FakeAgent(seq([instr(tasks=(tcard("bad", "attack prod", affected_target="10.0.0.5"),)), instr(propose=True)]))
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("accept")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    led = load(result.run_id, runs_root=tmp_path)
    assert led.nodes["bad"].status is NodeStatus.REJECTED
    assert executor.calls == []  # never dispatched against the off-scope host


@pytest.mark.asyncio
async def test_unparseable_executor_output_becomes_failed_node(tmp_path: Path) -> None:
    instructor = FakeAgent(seq([instr(tasks=(tcard("p", "probe"),)), instr(propose=True)]))
    executor = FakeAgent(always(None))  # structured_output=None (Codex-style silent failure)
    judge = FakeAgent(always(verdict("accept")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    led = load(result.run_id, runs_root=tmp_path)
    assert led.nodes["p"].status is NodeStatus.FAILED
    assert led.nodes["p"].failure_reason is not None
    assert "unparseable" in led.nodes["p"].failure_reason


@pytest.mark.asyncio
async def test_executor_exception_is_isolated_to_its_leaf(tmp_path: Path) -> None:
    instructor = FakeAgent(seq([instr(tasks=(tcard("a", "probe a"), tcard("b", "probe b"))), instr(propose=True)]))
    executor = FakeAgent(by_text([("probe a", RuntimeError("boom")), ("probe b", evidence())]))
    judge = FakeAgent(always(verdict("accept")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    led = load(result.run_id, runs_root=tmp_path)
    assert led.nodes["a"].status is NodeStatus.FAILED
    assert led.nodes["b"].status is NodeStatus.DONE


@pytest.mark.asyncio
async def test_true_negative_endpoint_is_not_flagged(tmp_path: Path) -> None:
    instructor = FakeAgent(seq([instr(tasks=(tcard("p", "probe hardened"),)), instr(propose=True)]))
    executor = FakeAgent(always(evidence(observations=("200 OK, nothing reflected",))))
    judge = FakeAgent(always(verdict("accept")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    assert not result.accepted_findings
    assert "No findings were accepted." in Path(result.report_path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_completion_with_pending_tasks_runs_tasks_first(tmp_path: Path) -> None:
    # instructor prematurely claims completion AND proposes a task in the same turn
    instructor = FakeAgent(seq([instr(propose=True, tasks=(tcard("p", "probe"),)), instr(propose=True)]))
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("accept")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    assert executor.calls  # the task ran; completion did not short-circuit the work
    assert result.completed is True


@pytest.mark.asyncio
async def test_unsatisfiable_dependency_terminates_as_deadlock(tmp_path: Path) -> None:
    instructor = FakeAgent(always(instr(tasks=(tcard("a", "probe a", depends_on=("missing",)),))))
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("accept")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    assert result.reason == "deadlock_blocked"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_cyclic_dependency_is_marked_failed(tmp_path: Path) -> None:
    instructor = FakeAgent(
        seq([instr(tasks=(tcard("a", "probe a", depends_on=("b",)), tcard("b", "probe b", depends_on=("a",)))), instr(propose=True)])
    )
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("accept")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    led = load(result.run_id, runs_root=tmp_path)
    assert led.nodes["a"].status is NodeStatus.FAILED
    assert led.nodes["b"].status is NodeStatus.FAILED


@pytest.mark.asyncio
async def test_needs_more_budget_caps_verifications(tmp_path: Path) -> None:
    instructor = FakeAgent(seq([instr(tasks=(tcard("p", "probe"),)), instr(propose=True)]))
    executor = FakeAgent(by_text([("reproduce", evidence()), ("probe", evidence(findings=(cand(),)))], default=evidence()))
    judge = FakeAgent(
        by_text([("COMPLETION", verdict("accept"))], default=verdict("needs_more", vinstr="reproduce", vtarget="127.0.0.1:8000"))
    )

    result = await build(
        instructor, executor, judge, runs_root=tmp_path, config=FrameworkConfig(max_rounds=4, max_finding_verifications=2)
    ).run("goal")

    led = load(result.run_id, runs_root=tmp_path)
    assert led.verifier_counts.get("p-f0") == 2  # capped
    assert any(fid == "p-f0" for fid, _ in led.rejected_findings)  # auto-rejected, no livelock


@pytest.mark.asyncio
async def test_dispatch_budget_terminates_the_run(tmp_path: Path) -> None:
    instructor = FakeAgent(lambda task, idx: instr(tasks=(tcard(f"t{idx}", f"probe {idx}"),)))
    executor = FakeAgent(always(evidence()))
    judge = FakeAgent(always(verdict("accept")))

    result = await build(
        instructor, executor, judge, runs_root=tmp_path, config=FrameworkConfig(max_rounds=99, max_total_dispatches=3)
    ).run("goal")

    assert result.reason == "dispatch_budget_exhausted"
    assert len(executor.calls) <= 3


@pytest.mark.asyncio
async def test_finding_with_out_of_scope_target_is_rejected_unjudged(tmp_path: Path) -> None:
    instructor = FakeAgent(seq([instr(tasks=(tcard("p", "probe"),)), instr(propose=True)]))
    executor = FakeAgent(by_text([("probe", evidence(findings=(cand(target="10.0.0.5"),)))], default=evidence()))
    judge = FakeAgent(by_text([("COMPLETION", verdict("accept"))], default=verdict("accept")))

    result = await build(instructor, executor, judge, runs_root=tmp_path).run("goal")

    led = load(result.run_id, runs_root=tmp_path)
    assert any(fid == "p-f0" for fid, _ in led.rejected_findings)
    assert "p-f0" not in led.accepted_finding_ids
    # the judge was never asked to rule on the out-of-scope finding (only completion)
    assert all("FINDING REVIEW" not in str(c.task) for c in judge.calls)
