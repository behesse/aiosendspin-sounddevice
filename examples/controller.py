"""Example demonstrating controller functionality."""

import asyncio
from aiosendspin_sounddevice import SendspinAudioClient, SendspinAudioClientConfig


async def main():
    """Connect and demonstrate controller commands."""
    config = SendspinAudioClientConfig(
        url="ws://localhost:8927/sendspin",
        client_id="controller-client",
        client_name="Controller Example",
    )

    client = SendspinAudioClient(config)

    try:
        await client.connect()
        print("Connected! Waiting for server state...")
        await asyncio.sleep(2)  # Wait for initial state

        # Check supported commands
        supported = client.get_supported_commands()
        print(f"Supported commands: {[cmd.value for cmd in supported]}")

        # Demonstrate controller commands
        print("\n=== Controller Commands ===")

        # Play/Pause toggle
        print("\n1. Toggling play/pause...")
        await client.toggle_play_pause()
        await asyncio.sleep(1)

        # Individual commands
        if "PLAY" in [cmd.value for cmd in supported]:
            print("2. Sending PLAY command...")
            await client.play()
            await asyncio.sleep(1)

        if "PAUSE" in [cmd.value for cmd in supported]:
            print("3. Sending PAUSE command...")
            await client.pause()
            await asyncio.sleep(1)

        if "NEXT" in [cmd.value for cmd in supported]:
            print("4. Sending NEXT track command...")
            await client.next_track()
            await asyncio.sleep(1)

        if "PREVIOUS" in [cmd.value for cmd in supported]:
            print("5. Sending PREVIOUS track command...")
            await client.previous_track()
            await asyncio.sleep(1)

        if "SWITCH" in [cmd.value for cmd in supported]:
            print("6. Sending SWITCH group command...")
            await client.switch_group()
            await asyncio.sleep(1)

        # Monitor state
        print("\n=== Current State ===")
        print(client.describe_state())

        print("\nPlaying audio... Press Ctrl+C to stop")
        try:
            await client.wait_for_disconnect()
        except asyncio.CancelledError:
            pass

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

