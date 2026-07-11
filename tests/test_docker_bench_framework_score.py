from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "benchmark" / "pilot" / "run_docker_bench.py"
    spec = importlib.util.spec_from_file_location("run_docker_bench_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_framework_score_uses_only_accepted_ledger_findings(tmp_path: Path) -> None:
    runner = _load_runner()
    flag = "FLAG{accepted}"
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "ledger.json").write_text(
        json.dumps(
            {
                "accepted_finding_ids": ["good"],
                "findings": [
                    {
                        "id": "good",
                        "title": "flag recovered",
                        "affected_target": "http://target",
                        "description": "accepted flag finding",
                        "evidence_excerpt": flag,
                    },
                    {
                        "id": "bad",
                        "title": "unaccepted flag",
                        "affected_target": "http://target",
                        "description": "should not count",
                        "evidence_excerpt": "FLAG{rejected}",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    scored_text = runner._framework_report_text(tmp_path)
    assert flag in scored_text
    assert "FLAG{rejected}" not in scored_text

    scored = runner.score_framework("", runner.COMBOS[0], flag, True, scored_text)
    assert scored["solved"] is True
    assert scored["status"] == "SOLVED"


def test_runner_classifies_new_failure_statuses() -> None:
    runner = _load_runner()

    assert runner._failure_class("COMPOSE_UP_ERROR") == "infra"
    assert runner._failure_class("LIVENESS_ERROR") == "infra"
    assert runner._failure_class("AUTH_ERROR") == "auth"
    assert runner._failure_class("PROVIDER_NETWORK_ERROR") == "provider_network"
    assert runner._failure_class("EARLY_EXIT") == "early_exit"


def test_runner_detects_provider_auth_and_network_failures() -> None:
    runner = _load_runner()

    assert runner._auth_failed("Failed to authenticate. API Error: 403 Request not allowed")
    assert runner._provider_network_failed(
        "stream disconnected before completion: error sending request for url "
        "(https://chatgpt.com/backend-api/codex/responses)"
    )


def test_compose_up_uses_no_build(monkeypatch) -> None:
    runner = _load_runner()
    seen: list[list[str]] = []

    def fake_sync(cmd, cwd=None, timeout=None):
        seen.append(cmd)
        return runner.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(runner, "_sync", fake_sync)

    ok, why = runner.compose_up("XBEN-001-24")

    assert ok is True
    assert why == "ok"
    assert seen
    assert "--no-build" in seen[0]


def test_dedupe_benchmarks_rejects_duplicates() -> None:
    runner = _load_runner()

    assert runner._dedupe_benchmarks([" XBEN-001-24 ", "", "XBEN-068-24"]) == [
        "XBEN-001-24",
        "XBEN-068-24",
    ]

    try:
        runner._dedupe_benchmarks(["XBEN-001-24", "XBEN-001-24"])
    except ValueError as exc:
        assert "duplicate benchmark" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected duplicate benchmark rejection")


def test_declared_host_ports_ignores_ephemeral_and_expose(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner()
    bench = tmp_path / "XBEN-PORTS"
    bench.mkdir()
    (bench / "docker-compose.yml").write_text(
        """
services:
  web:
    image: example/web
    ports:
      - 80
      - "127.0.0.1:8080:80"
      - "5000:5000/tcp"
      - "9000-9001:90"
  dns:
    image: example/dns
    ports:
      - target: 53
        published: 5353
        protocol: udp
  db:
    image: example/db
    expose:
      - "3306:3306"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "BENCH_ROOT", tmp_path)

    assert runner.declared_host_ports("XBEN-PORTS") == {
        "tcp:5000",
        "tcp:8080",
        "tcp:9000",
        "tcp:9001",
        "udp:5353",
    }


def test_docker_preflight_fails_fast(monkeypatch) -> None:
    runner = _load_runner()
    calls: list[list[str]] = []

    def fake_sync(cmd, cwd=None, timeout=None):
        calls.append(cmd)
        if cmd[:2] == ["docker", "info"]:
            return runner.subprocess.CompletedProcess(cmd, 1, "", "daemon unavailable")
        return runner.subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(runner, "_sync", fake_sync)

    ok, why = runner.docker_preflight("pentestgpt:latest")

    assert ok is False
    assert "docker info failed" in why
    assert calls == [["docker", "version"], ["docker", "info"]]
