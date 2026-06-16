"""Tests for the one-shot (single-agent) CTF prompt builders.

These builders back the "pure single agent" benchmark baseline
(benchmark/pilot/run_docker_bench.py --variant single): the staged pipeline's
prompt fragments collapsed into one turn. The point of the baseline is that the
prompt *content* matches the pipeline, so these tests assert the key fragments
survive the collapse.
"""

from __future__ import annotations

import pytest

from pentestgpt.core.config import PentestGPTConfig
from pentestgpt.prompts.stages import (
    ctf_single_agent_system_prompt,
    ctf_single_agent_task_prompt,
)


@pytest.mark.unit
class TestSingleAgentPrompts:
    def test_system_prompt_contains_shared_fragments(self):
        """The one-shot system prompt must reuse the pipeline's rich fragments."""
        cfg = PentestGPTConfig(target="10.10.11.234")
        sp = ctf_single_agent_system_prompt(cfg)
        for fragment in (
            "You are PentestGPT",          # _IDENTITY
            "CTF CHALLENGE CATEGORIES",     # _CTF_CATEGORIES
            "TOOLS & CAPABILITIES",         # _TOOLS
            "NEVER GIVE UP",                # _PERSISTENCE
            "FALLBACK STRATEGIES",          # _FALLBACK_STRATEGIES
            "FLAG PATTERNS TO RECOGNIZE",   # _FLAG_PATTERNS
        ):
            assert fragment in sp, f"missing fragment: {fragment}"

    def test_system_prompt_is_single_turn(self):
        """It should frame the work as one session, not a multi-stage handoff."""
        cfg = PentestGPTConfig(target="10.10.11.234")
        sp = ctf_single_agent_system_prompt(cfg)
        assert "SINGLE session" in sp
        # The walkthrough/documentation stage is intentionally dropped.
        assert "WALKTHROUGH FORMAT" not in sp

    def test_custom_instruction_appended(self):
        """A custom instruction (challenge hint) is appended like the staged builders."""
        cfg = PentestGPTConfig(target="10.10.11.234", custom_instruction="hint: idor on /api")
        sp = ctf_single_agent_system_prompt(cfg)
        assert "hint: idor on /api" in sp

    def test_task_prompt_includes_target(self):
        cfg = PentestGPTConfig(target="http://172.28.0.2:80")
        tp = ctf_single_agent_task_prompt(cfg)
        assert "http://172.28.0.2:80" in tp
        assert "capture ALL flags" in tp
