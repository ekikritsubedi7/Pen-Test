"""Regression tests for legacy session path containment (#502)."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from rich.console import Console

from pentestgpt_legacy.utils import pentest_gpt as pentest_gpt_mod
from pentestgpt_legacy.utils.pentest_gpt import pentestGPT, resolve_session_save_path

pytestmark = pytest.mark.unit


def test_resolve_rejects_traversal(tmp_path) -> None:
    root = tmp_path / "test_history"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_session_save_path(str(root), "../outside.json")


def test_resolve_rejects_nested(tmp_path) -> None:
    root = tmp_path / "test_history"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_session_save_path(str(root), "nested/session.json")


def test_resolve_rejects_absolute(tmp_path) -> None:
    root = tmp_path / "test_history"
    root.mkdir()
    absolute = str(tmp_path / "elsewhere.json")
    with pytest.raises(ValueError):
        resolve_session_save_path(str(root), absolute)


def test_resolve_accepts_plain_filename(tmp_path) -> None:
    root = tmp_path / "test_history"
    root.mkdir()
    path = resolve_session_save_path(str(root), "session.json")
    assert path == os.path.realpath(str(root / "session.json"))
    assert os.path.dirname(path) == os.path.realpath(str(root))


def test_resolve_rejects_dot_and_dotdot(tmp_path) -> None:
    root = tmp_path / "test_history"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_session_save_path(str(root), ".")
    with pytest.raises(ValueError):
        resolve_session_save_path(str(root), "..")


def _session_stub(monkeypatch: pytest.MonkeyPatch, cwd: Any, answers: list[str]) -> pentestGPT:
    """Build a minimal pentestGPT without LLM clients."""
    session = object.__new__(pentestGPT)
    session.save_dir = "test_history"
    session.task_log = {"step": 1}
    session.history = {"user": [(1.0, "hi")]}
    session.console = Console(force_terminal=False)
    monkeypatch.chdir(cwd)
    queue = list(answers)

    def fake_prompt_ask(_prompt: str, multiline: bool = False) -> str:
        del _prompt, multiline
        assert queue, "prompt_ask called with no remaining answers"
        return queue.pop(0)

    monkeypatch.setattr(pentest_gpt_mod, "prompt_ask", fake_prompt_ask)
    return session


def test_save_session_reprompts_and_stays_in_test_history(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside.json"
    session = _session_stub(
        monkeypatch,
        tmp_path,
        answers=["../outside.json", "nested/session.json", "good-session.json"],
    )
    session.save_session()

    assert not outside.exists()
    saved = tmp_path / "test_history" / "good-session.json"
    assert saved.is_file()
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload == {"task_log": {"step": 1}, "history": {"user": [[1.0, "hi"]]}}


def test_save_session_empty_name_uses_timestamp(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pentest_gpt_mod.time, "time", lambda: 12345.0)
    session = _session_stub(monkeypatch, tmp_path, answers=[""])
    session.save_session()
    saved = tmp_path / "test_history" / "12345.0"
    assert saved.is_file()
