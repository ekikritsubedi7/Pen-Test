import asyncio
import time
from typing import Any

import pytest

from pentestgpt_agent import AgentLoop, LoopConfig
from unified_agent import Task, UnifiedResult, UnifiedUsage


def make_result(
    *,
    success: bool = True,
    text: str = "",
    structured_output: Any | None = None,
    error: str | None = None,
) -> UnifiedResult:
    return UnifiedResult(
        backend="fake",
        success=success,
        text=text,
        structured_output=structured_output,
        usage=UnifiedUsage(),
        cost_usd=None,
        session_id=None,
        duration_ms=None,
        tool_calls=[],
        file_changes=[],
        events=[],
        error=error,
    )


def instruction_output(
    *,
    done: bool = False,
    final_message: str = "",
    tasks: list[dict[str, Any]] | None = None,
) -> UnifiedResult:
    return make_result(
        structured_output={
            "done": done,
            "final_message": final_message,
            "tasks": tasks or [],
        }
    )


class FakeAgent:
    def __init__(self, outputs: list[UnifiedResult], delay: float = 0.0) -> None:
        self.outputs = list(outputs)
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        task: Task | str,
        *,
        output_schema: dict[str, Any] | None = None,
        resume: str | None = None,
        max_turns: int | None = None,
    ) -> UnifiedResult:
        call_index = len(self.calls)
        self.calls.append(
            {
                "task": task,
                "output_schema": output_schema,
                "resume": resume,
                "max_turns": max_turns,
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if call_index < len(self.outputs):
            return self.outputs[call_index]
        return self.outputs[-1]


@pytest.mark.asyncio
async def test_loop_runs_task_card_then_stops_when_instructor_is_done() -> None:
    instructor = FakeAgent(
        [
            instruction_output(tasks=[{"id": "t1", "instruction": "Compute the local answer."}]),
            instruction_output(done=True, final_message="done"),
        ]
    )
    executor = FakeAgent([make_result(text="local answer is 42")])

    result = await AgentLoop(instructor, {"exec": executor}).run("Find answer")

    assert result.success is True
    assert result.done is True
    assert result.final_message == "done"
    assert len(result.executions) == 1
    assert result.executions[0].task.id == "t1"
    assert "local answer is 42" in instructor.calls[1]["task"]


@pytest.mark.asyncio
async def test_executor_receives_only_task_card_content() -> None:
    secret_goal = "GLOBAL SECRET SHOULD NOT REACH EXECUTOR"
    instructor = FakeAgent(
        [
            instruction_output(
                tasks=[
                    {
                        "id": "narrow",
                        "instruction": "Run only this narrow task.",
                        "context": "Only local context.",
                    }
                ]
            )
        ]
    )
    executor = FakeAgent([make_result(text="ok")])

    await AgentLoop(instructor, {"exec": executor}, LoopConfig(max_rounds=1)).run(secret_goal)

    task = executor.calls[0]["task"]
    assert isinstance(task, Task)
    assert task.instruction == "Run only this narrow task."
    assert task.context == "Only local context."
    assert secret_goal not in task.instruction
    assert secret_goal not in (task.context or "")


@pytest.mark.asyncio
async def test_executor_calls_are_fresh_and_use_turn_limits() -> None:
    instructor = FakeAgent(
        [
            instruction_output(
                tasks=[
                    {
                        "id": "bounded",
                        "instruction": "Do bounded work.",
                        "max_turns": 7,
                    }
                ]
            )
        ]
    )
    executor = FakeAgent([make_result(text="ok")])
    config = LoopConfig(max_rounds=1, instructor_max_turns=2, executor_max_turns=9)

    await AgentLoop(instructor, {"exec": executor}, config).run("Goal")

    assert instructor.calls[0]["resume"] is None
    assert instructor.calls[0]["max_turns"] == 2
    assert instructor.calls[0]["output_schema"] is not None
    assert executor.calls[0]["resume"] is None
    assert executor.calls[0]["max_turns"] == 7


@pytest.mark.asyncio
async def test_task_cards_run_concurrently() -> None:
    instructor = FakeAgent(
        [
            instruction_output(
                tasks=[
                    {"id": "a", "instruction": "Task A"},
                    {"id": "b", "instruction": "Task B"},
                ]
            )
        ]
    )
    executor = FakeAgent([make_result(text="a"), make_result(text="b")], delay=0.2)

    started = time.monotonic()
    result = await AgentLoop(instructor, {"exec": executor}, LoopConfig(max_rounds=1)).run("Goal")
    elapsed = time.monotonic() - started

    assert result.success is True
    assert len(result.executions) == 2
    assert elapsed < 0.35


@pytest.mark.asyncio
async def test_unknown_executor_fails_before_running_tasks() -> None:
    instructor = FakeAgent(
        [
            instruction_output(
                tasks=[
                    {
                        "id": "bad",
                        "instruction": "Use missing executor.",
                        "executor": "missing",
                    }
                ]
            )
        ]
    )
    executor = FakeAgent([make_result(text="should not run")])

    result = await AgentLoop(instructor, {"exec": executor}).run("Goal")

    assert result.success is False
    assert result.error == "unknown executor: missing"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_done_instructor_response_skips_executors() -> None:
    instructor = FakeAgent([instruction_output(done=True, final_message="already done")])
    executor = FakeAgent([make_result(text="should not run")])

    result = await AgentLoop(instructor, {"exec": executor}).run("Goal")

    assert result.success is True
    assert result.done is True
    assert result.final_message == "already done"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_max_rounds_stops_repeated_planning() -> None:
    instructor = FakeAgent(
        [
            instruction_output(tasks=[{"id": "again", "instruction": "Do it again."}]),
        ]
    )
    executor = FakeAgent([make_result(text="not enough")])

    result = await AgentLoop(instructor, {"exec": executor}, LoopConfig(max_rounds=2)).run("Goal")

    assert result.success is True
    assert result.done is False
    assert len(instructor.calls) == 2
    assert len(executor.calls) == 2


@pytest.mark.asyncio
async def test_invalid_instructor_structured_output_fails() -> None:
    instructor = FakeAgent([make_result(structured_output={"done": "nope"})])
    executor = FakeAgent([make_result(text="should not run")])

    result = await AgentLoop(instructor, {"exec": executor}).run("Goal")

    assert result.success is False
    assert "done" in (result.error or "")
    assert executor.calls == []


@pytest.mark.asyncio
async def test_executor_failure_is_summarized_to_next_instructor_round() -> None:
    instructor = FakeAgent(
        [
            instruction_output(tasks=[{"id": "fragile", "instruction": "Try fragile thing."}]),
            instruction_output(done=True, final_message="stop"),
        ]
    )
    executor = FakeAgent([make_result(success=False, error="boom", text="partial")])

    result = await AgentLoop(instructor, {"exec": executor}).run("Goal")

    assert result.success is True
    assert result.done is True
    assert "status=failed" in instructor.calls[1]["task"]
    assert "partial" in instructor.calls[1]["task"]
