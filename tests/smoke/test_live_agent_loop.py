import os

import pytest

from pentestgpt_agent import AgentLoop, LoopConfig
from unified_agent import SandboxPolicy, UnifiedAgent

pytestmark = [pytest.mark.live, pytest.mark.slow]

if os.getenv("PENTESTGPT_LIVE_SMOKE") != "1":
    pytest.skip(
        "set PENTESTGPT_LIVE_SMOKE=1 to run live Claude/Codex smoke tests",
        allow_module_level=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("instructor_backend", "executor_backend"),
    [("claude", "codex"), ("codex", "claude")],
)
async def test_live_instructor_executor_loop(
    tmp_path, instructor_backend: str, executor_backend: str
) -> None:
    instructor = UnifiedAgent(
        backend=instructor_backend,
        workspace=tmp_path / f"instructor-{instructor_backend}",
        sandbox=SandboxPolicy.WORKSPACE_WRITE,
        instructions=(
            "Be literal. On the first round, set done=false and create exactly one task. "
            "After prior execution says 42, set done=true and final_message must include 42."
        ),
    )
    executor = UnifiedAgent(
        backend=executor_backend,
        workspace=tmp_path / f"executor-{executor_backend}",
        sandbox=SandboxPolicy.WORKSPACE_WRITE,
        instructions="Answer with the requested value only.",
    )
    loop = AgentLoop(
        instructor=instructor,
        executors={"exec": executor},
        config=LoopConfig(max_rounds=3, instructor_max_turns=4, executor_max_turns=4),
    )

    result = await loop.run(
        "Use an executor to compute 20.25 + 21.75. "
        "The executor task should ask for the numeric answer only."
    )

    combined = result.final_message + "\n" + "\n".join(r.result.text for r in result.executions)
    assert result.success, result.error
    assert result.done
    assert result.executions
    assert "42" in combined
