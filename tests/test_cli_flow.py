"""Test CLI flow to debug NoneType await issue."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_run_pentest_dry():
    """Test run_pentest without actually connecting to Claude."""
    print("Testing run_pentest function...")

    try:
        from pentestgpt.core.agent import run_pentest

        print(f"  ✓ run_pentest imported: {run_pentest}")
        print(f"  ✓ Is coroutine function: {asyncio.iscoroutinefunction(run_pentest)}")

        # We can't actually run it without Claude SDK, but we can check the function exists
        return True

    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_controller_creation():
    """Test AgentController creation."""
    print("\nTesting AgentController creation...")

    try:
        from pentestgpt.core.config import load_config
        from pentestgpt.core.controller import AgentController, AgentState

        config = load_config(target="test.example.com")
        print(f"  ✓ Config created: {config}")

        controller = AgentController(config)
        print(f"  ✓ Controller created: {controller}")
        print(f"  ✓ Controller state: {controller.state}")

        # Check if run is a coroutine function
        print(
            f"  ✓ controller.run is coroutine function: {asyncio.iscoroutinefunction(controller.run)}"
        )

        return True

    except Exception as e:
        print(f"  ✗ Controller creation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_backend_creation():
    """Test ClaudeCodeBackend creation (without connect)."""
    print("\nTesting ClaudeCodeBackend creation...")

    try:
        from pentestgpt.core.backend import ClaudeCodeBackend
        from pentestgpt.prompts.pentesting import get_ctf_prompt

        backend = ClaudeCodeBackend(
            working_directory="/workspace",
            system_prompt=get_ctf_prompt(None),
            model="claude-sonnet-4-5-20250929",
        )
        print(f"  ✓ Backend created: {backend}")

        # Check if methods are coroutine functions
        print(
            f"  ✓ connect is coroutine function: {asyncio.iscoroutinefunction(backend.connect)}"
        )
        print(
            f"  ✓ query is coroutine function: {asyncio.iscoroutinefunction(backend.query)}"
        )
        print(
            f"  ✓ disconnect is coroutine function: {asyncio.iscoroutinefunction(backend.disconnect)}"
        )

        return True

    except Exception as e:
        print(f"  ✗ Backend creation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_event_bus():
    """Test EventBus."""
    print("\nTesting EventBus...")

    try:
        from pentestgpt.core.events import EventBus, EventType, Event

        bus = EventBus.get()
        print(f"  ✓ EventBus singleton: {bus}")

        # Test emit
        events_received = []

        def handler(event):
            events_received.append(event)

        bus.subscribe(EventType.MESSAGE, handler)
        bus.emit_message("Test message")

        if len(events_received) == 1:
            print(f"  ✓ Event emitted and received: {events_received[0]}")
        else:
            print(f"  ✗ Expected 1 event, got {len(events_received)}")

        # Reset for clean state
        EventBus.reset()
        return True

    except Exception as e:
        print(f"  ✗ EventBus test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("PentestGPT CLI Flow Debug Tests")
    print("=" * 60)

    all_passed = True

    if not await test_run_pentest_dry():
        all_passed = False

    if not await test_controller_creation():
        all_passed = False

    if not await test_backend_creation():
        all_passed = False

    if not await test_event_bus():
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("All CLI flow tests passed!")
    else:
        print("Some tests failed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
