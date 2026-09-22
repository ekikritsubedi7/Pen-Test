"""Interactive search reaches the actual MCP client and displays cited results."""

from __future__ import annotations

import json
from io import StringIO

import httpx
import pytest
from rich.console import Console

from pentestgpt_legacy.utils import pentest_gpt, web_search


@pytest.mark.asyncio
async def test_search_uses_parallel_mcp_with_project_identity() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        message = json.loads(request.content)
        method = message["method"]
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fixture", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "web_search",
                        "description": "Search the web",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "objective": {"type": "string"},
                                "search_queries": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["objective", "search_queries"],
                        },
                        "outputSchema": {
                            "type": "object",
                            "properties": {"results": {"type": "array"}},
                        },
                    }
                ]
            }
        elif method == "tools/call":
            result = {
                "content": [],
                "structuredContent": {
                    "results": [
                        {
                            "title": "Official reference",
                            "url": "https://example.org/reference",
                            "excerpts": ["A useful finding."],
                        }
                    ]
                },
                "isError": False,
            }
        else:
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": message["id"], "result": result},
            headers={"Content-Type": "application/json"},
        )

    output = await web_search._search(
        "public reference",
        endpoint="https://example.org/mcp",
        transport=httpx.MockTransport(respond),
    )

    calls = [json.loads(request.content) for request in requests]
    assert [call["method"] for call in calls] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
        "tools/list",
    ]
    assert calls[2]["params"] == {
        "name": "web_search",
        "arguments": {"objective": "public reference", "search_queries": ["public reference"]},
    }
    assert all(
        request.headers["user-agent"] == "PentestGPT/1.0.0 mcp-python" for request in requests
    )
    assert all("authorization" not in request.headers for request in requests)
    assert "https://example.org/reference" in output
    assert "A useful finding." in output


@pytest.mark.parametrize("local", [False, True])
def test_interactive_search_command_shows_results(
    monkeypatch: pytest.MonkeyPatch, local: bool
) -> None:
    agent = object.__new__(pentest_gpt.pentestGPT)
    output = StringIO()
    agent.console = Console(file=output)
    agent.chat_count = 0
    agent.history = {"user": [], "pentestGPT": []}
    monkeypatch.setattr(pentest_gpt, "prompt_ask", lambda *args, **kwargs: "public reference")
    monkeypatch.setattr(
        pentest_gpt, "search_web", lambda query: f"Result: {query}\nhttps://example.org/reference"
    )
    if local:
        monkeypatch.setattr(pentest_gpt, "local_task_entry", lambda: "search")
        result = agent.local_input_handler()
    else:
        monkeypatch.setattr(pentest_gpt, "main_task_entry", lambda: "search")
        result = agent.input_handler()

    assert "https://example.org/reference" in result
    assert "https://example.org/reference" in output.getvalue()
    assert agent.history["user"][-1][1] == "Web search: public reference"
