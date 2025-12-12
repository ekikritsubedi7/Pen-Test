"""Test file to debug the NoneType await issue."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_sdk_methods():
    """Test if Claude SDK methods are awaitable."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    print("Creating ClaudeAgentOptions...")
    options = ClaudeAgentOptions(
        cwd="/workspace",
        permission_mode="bypassPermissions",
        system_prompt="You are a test agent.",
        model="claude-sonnet-4-5-20250929",
    )

    print("Creating ClaudeSDKClient...")
    client = ClaudeSDKClient(options=options)

    print(f"client.connect type: {type(client.connect)}")
    print(f"client.query type: {type(client.query)}")

    # Check if connect returns an awaitable
    connect_result = client.connect()
    print(f"client.connect() returned: {type(connect_result)}")

    if connect_result is None:
        print("ERROR: client.connect() returns None - it's synchronous!")
    else:
        print("Awaiting connect()...")
        await connect_result

    # Check query
    query_result = client.query("Hello")
    print(f"client.query() returned: {type(query_result)}")

    if query_result is None:
        print("ERROR: client.query() returns None - it's synchronous!")
    else:
        print("Awaiting query()...")
        await query_result

    # Cleanup
    disconnect_result = client.disconnect()
    print(f"client.disconnect() returned: {type(disconnect_result)}")
    if disconnect_result is not None:
        await disconnect_result

    print("Test complete!")


async def test_controller():
    """Test the controller directly."""
    from pentestgpt.core.config import load_config
    from pentestgpt.core.controller import AgentController

    print("\n=== Testing AgentController ===")
    config = load_config(target="test.example.com")
    controller = AgentController(config)

    print("Running controller...")
    try:
        result = await controller.run("Test task")
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print("Testing Claude SDK methods...")
    try:
        asyncio.run(test_sdk_methods())
    except Exception as e:
        print(f"SDK test failed: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 60 + "\n")

    print("Testing controller...")
    try:
        asyncio.run(test_controller())
    except Exception as e:
        print(f"Controller test failed: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
