"""Tests for AgentController."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from pentestgpt.core.backend import AgentBackend, AgentMessage, MessageType
from pentestgpt.core.config import PentestGPTConfig
from pentestgpt.core.controller import AgentController, AgentState
from pentestgpt.core.events import EventBus
from pentestgpt.core.session import SessionStore


class MockBackend(AgentBackend):
    """Mock backend for testing."""

    def __init__(self):
        self._connected = False
        self._messages = []
        self._session_id = "mock-session-123"

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def query(self, prompt: str) -> None:
        pass

    async def receive_messages(self):
        for msg in self._messages:
            yield msg

    @property
    def session_id(self):
        return self._session_id

    @property
    def supports_resume(self) -> bool:
        return False

    async def resume(self, session_id: str) -> bool:
        return False

    def set_messages(self, messages):
        """Set messages to be returned by receive_messages."""
        self._messages = messages


class TestAgentController:
    """Tests for AgentController."""

    @pytest.fixture(autouse=True)
    def reset_event_bus(self):
        """Reset EventBus singleton."""
        EventBus.reset()
        yield
        EventBus.reset()

    @pytest.fixture
    def temp_sessions_dir(self):
        """Create temp directory for sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def config(self):
        """Create test config."""
        return PentestGPTConfig(
            target="test.example.com",
            working_directory=Path("/tmp/pentestgpt-test"),
        )

    @pytest.fixture
    def mock_backend(self):
        """Create mock backend."""
        return MockBackend()

    @pytest.fixture
    def controller(self, config, mock_backend, temp_sessions_dir):
        """Create controller with mock backend."""
        session_store = SessionStore(sessions_dir=temp_sessions_dir)
        return AgentController(
            config=config,
            backend=mock_backend,
            session_store=session_store,
        )

    def test_initial_state(self, controller):
        """Test controller starts in idle state."""
        assert controller.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_run_success(self, controller, mock_backend):
        """Test successful run."""
        # Set up messages
        mock_backend.set_messages(
            [
                AgentMessage(type=MessageType.TEXT, content="Starting task..."),
                AgentMessage(type=MessageType.TEXT, content="Found flag{test123}!"),
                AgentMessage(
                    type=MessageType.RESULT, content=None, metadata={"cost_usd": 0.5}
                ),
            ]
        )

        result = await controller.run("Test task")

        assert result["success"] is True
        assert "flag{test123}" in result["flags_found"]
        assert result["session_id"] is not None

    @pytest.mark.asyncio
    async def test_run_with_tool_messages(self, controller, mock_backend):
        """Test run with tool messages."""
        mock_backend.set_messages(
            [
                AgentMessage(
                    type=MessageType.TOOL_START,
                    content=None,
                    tool_name="bash",
                    tool_args={"command": "nmap -sV target"},
                ),
                AgentMessage(
                    type=MessageType.TOOL_RESULT,
                    content="PORT STATE SERVICE\n22 open ssh",
                    tool_name="bash",
                ),
                AgentMessage(type=MessageType.RESULT, content=None, metadata={}),
            ]
        )

        result = await controller.run("Scan target")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_pause_and_resume(self, controller, mock_backend):
        """Test pause and resume functionality."""

        async def slow_messages():
            for i in range(5):
                yield AgentMessage(type=MessageType.TEXT, content=f"Message {i}")
                if i == 2:
                    # Simulate pause request
                    controller.pause()
                    await asyncio.sleep(0.1)
                    # Resume
                    controller.resume()

        mock_backend.receive_messages = slow_messages

        result = await controller.run("Test task")
        assert result["success"] is True

    def test_pause_request(self, controller):
        """Test pause request in wrong state."""
        # Can't pause when idle
        assert controller.pause() is False

    def test_resume_request(self, controller):
        """Test resume request in wrong state."""
        # Can't resume when idle
        assert controller.resume() is False

    def test_stop_request(self, controller):
        """Test stop request."""
        assert controller.stop() is True

    @pytest.mark.asyncio
    async def test_stop_during_run(self, controller, mock_backend):
        """Test stopping during run."""

        async def infinite_messages():
            i = 0
            while True:
                yield AgentMessage(type=MessageType.TEXT, content=f"Message {i}")
                i += 1
                if i == 3:
                    controller.stop()
                await asyncio.sleep(0.01)

        mock_backend.receive_messages = infinite_messages

        result = await controller.run("Test task")
        assert result["success"] is True

    def test_inject_instruction(self, controller):
        """Test inject instruction."""
        # Can't inject when idle
        assert controller.inject("New instruction") is False

    @pytest.mark.asyncio
    async def test_flag_detection(self, controller, mock_backend):
        """Test flag detection patterns."""
        mock_backend.set_messages(
            [
                AgentMessage(type=MessageType.TEXT, content="Found flag{abc123}"),
                AgentMessage(type=MessageType.TEXT, content="Also HTB{test_flag}"),
                AgentMessage(
                    type=MessageType.TEXT,
                    content="And 0123456789abcdef0123456789abcdef",
                ),
                AgentMessage(type=MessageType.RESULT, content=None, metadata={}),
            ]
        )

        result = await controller.run("Find flags")

        assert len(result["flags_found"]) == 3
        assert "flag{abc123}" in result["flags_found"]
        assert "HTB{test_flag}" in result["flags_found"]

    @pytest.mark.asyncio
    async def test_session_not_found(self, controller):
        """Test resuming non-existent session."""
        result = await controller.run("Task", resume_session_id="nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_backend_error(self, controller, mock_backend):
        """Test handling backend errors."""

        async def error_messages():
            raise Exception("Backend error")
            yield  # Make it a generator

        mock_backend.receive_messages = error_messages

        result = await controller.run("Test task")
        assert result["success"] is False
        assert "Backend error" in result["error"]
