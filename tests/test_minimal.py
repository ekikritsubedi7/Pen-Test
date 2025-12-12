"""Minimal test to debug the NoneType await issue."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_imports():
    """Test if all imports work."""
    print("Step 1: Testing basic imports...")
    try:
        from pentestgpt.core.session import SessionStore, SessionInfo, SessionStatus

        print("  ✓ session module imported")
    except Exception as e:
        print(f"  ✗ session import failed: {e}")
        return False

    try:
        from pentestgpt.core.events import EventBus, EventType, Event

        print("  ✓ events module imported")
    except Exception as e:
        print(f"  ✗ events import failed: {e}")
        return False

    try:
        from pentestgpt.core.backend import (
            AgentBackend,
            ClaudeCodeBackend,
            AgentMessage,
            MessageType,
        )

        print("  ✓ backend module imported")
    except Exception as e:
        print(f"  ✗ backend import failed: {e}")
        return False

    try:
        from pentestgpt.core.controller import AgentController, AgentState

        print("  ✓ controller module imported")
    except Exception as e:
        print(f"  ✗ controller import failed: {e}")
        return False

    try:
        from pentestgpt.interface.tui import run_tui, PentestGPTApp

        print("  ✓ tui module imported")
    except Exception as e:
        print(f"  ✗ tui import failed: {e}")
        return False

    return True


async def test_tui_creation():
    """Test if TUI app can be created."""
    print("\nStep 2: Testing TUI app creation...")
    try:
        from pentestgpt.interface.tui import PentestGPTApp

        app = PentestGPTApp(
            target="test.example.com",
            custom_instruction=None,
            model=None,
            debug=False,
            resume_session=None,
        )
        print(f"  ✓ PentestGPTApp created: {app}")
        print(f"  ✓ app.run_async type: {type(app.run_async)}")

        # Check if run_async() returns an awaitable
        coro = app.run_async()
        print(f"  ✓ app.run_async() returned: {type(coro)}")

        if coro is None:
            print("  ✗ ERROR: app.run_async() returns None!")
            return False

        # Cancel the coroutine to avoid running the full app
        coro.close()
        print("  ✓ Coroutine is valid and closeable")
        return True

    except Exception as e:
        print(f"  ✗ TUI creation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_session_store():
    """Test SessionStore operations."""
    print("\nStep 3: Testing SessionStore...")
    try:
        from pentestgpt.core.session import SessionStore

        store = SessionStore()
        print(f"  ✓ SessionStore created")

        # List sessions (should work even if empty)
        sessions = store.list_sessions()
        print(f"  ✓ list_sessions() returned {len(sessions)} sessions")

        # Get latest (might be None)
        latest = store.get_latest("test.example.com")
        print(f"  ✓ get_latest() returned: {latest}")

        return True

    except Exception as e:
        print(f"  ✗ SessionStore test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_run_tui_mode():
    """Test the run_tui_mode function flow."""
    print("\nStep 4: Testing run_tui_mode flow...")
    try:
        from argparse import Namespace
        from pentestgpt.core.session import SessionStore
        from pentestgpt.interface.tui import run_tui

        # Create mock args
        args = Namespace(
            target="test.example.com",
            instruction=None,
            model=None,
            debug=False,
            resume=False,
            session_id=None,
        )

        # Replicate run_tui_mode logic
        resume_session = args.session_id
        if args.resume and not resume_session:
            sessions = SessionStore()
            latest = sessions.get_latest(args.target)
            if latest:
                resume_session = latest.session_id
                print(f"  Would resume session: {resume_session}")

        print(f"  ✓ resume_session = {resume_session}")

        # Check run_tui
        print(f"  ✓ run_tui is: {run_tui}")
        print(
            f"  ✓ run_tui is coroutine function: {asyncio.iscoroutinefunction(run_tui)}"
        )

        return True

    except Exception as e:
        print(f"  ✗ run_tui_mode test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("PentestGPT Debug Test Suite")
    print("=" * 60)

    all_passed = True

    if not await test_imports():
        all_passed = False

    if not await test_tui_creation():
        all_passed = False

    if not await test_session_store():
        all_passed = False

    if not await test_run_tui_mode():
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("All tests passed!")
    else:
        print("Some tests failed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
