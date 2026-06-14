"""Importability + wiring smoke for the real-agent role layer.

The real backends are exercised by the live E2E smoke; here we only assert the
module imports cleanly (it is not covered by `make lint`) and that the role
defaults match the design (Claude everywhere; distinct system prompts).
"""

from __future__ import annotations

import inspect

from pentestgpt_agent.roles import (
    EXECUTOR_SYSTEM,
    INSTRUCTOR_SYSTEM,
    JUDGE_SYSTEM,
    RoleConfig,
    run_framework,
)


def test_role_config_defaults_to_claude() -> None:
    cfg = RoleConfig()
    assert cfg.instructor_backend == "claude"
    assert cfg.executor_backend == "claude"
    assert cfg.judge_backend == "claude"


def test_system_prompts_are_distinct_and_nonempty() -> None:
    prompts = {INSTRUCTOR_SYSTEM, EXECUTOR_SYSTEM, JUDGE_SYSTEM}
    assert len(prompts) == 3
    assert all(len(p) > 100 for p in prompts)


def test_executor_prompt_states_evidence_contract() -> None:
    # the executor must know its structured JSON is canonical, not prose
    assert "candidate_findings" in EXECUTOR_SYSTEM
    assert "prose is ignored" in EXECUTOR_SYSTEM


def test_run_framework_is_async() -> None:
    assert inspect.iscoroutinefunction(run_framework)
