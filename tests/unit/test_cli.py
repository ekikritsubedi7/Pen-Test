"""Tests for the PentestGPT command-line parser."""

import pytest

from pentestgpt.interface.main import parse_arguments


def test_target_required_for_pipeline_runs():
    with pytest.raises(SystemExit) as exc:
        parse_arguments([])

    assert exc.value.code == 2


def test_list_sessions_does_not_require_target():
    args = parse_arguments(["--list-sessions"])

    assert args.list_sessions is True
    assert args.target is None


def test_list_sessions_can_filter_by_target():
    args = parse_arguments(["--list-sessions", "--target", "example.com"])

    assert args.list_sessions is True
    assert args.target == "example.com"
