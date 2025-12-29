#!/usr/bin/env python3

import asyncio
import logging
from aiohttp import ClientError
from aiosendspin_sounddevice import (
    AudioDevice,
    AudioDeviceManager,
    SendspinAudioClient,
    SendspinAudioClientConfig,
)

# Setup logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


async def main():
    """Example: Connect to a Sendspin server and play audio with all features."""
    # List available audio devices
    print("Available audio devices:")
    devices = AudioDeviceManager.list_audio_devices()
    if not devices:
        print("No audio output devices found. Exiting.")
        return
    for i, device in enumerate(devices):
        print(f"  {i}: {device}")

    # Get default device or select one
    selected_device = next((d for d in devices if d.is_default), None)
    if selected_device:
        print(f"\nUsing default device: {selected_device.name}")
    else:
        selected_device = devices[0]
        print(f"\nUsing first available device: {selected_device.name}")

    # Define callbacks for state updates
    def on_metadata_update(metadata: dict) -> None:
        """Handle metadata updates."""
        print(f"Metadata: {metadata['title']} by {metadata['artist']} ({metadata['album']})")
        # Show progress in seconds format
        if metadata.get('track_duration'):
            track_progress = metadata.get('track_progress') or 0
            track_duration = metadata['track_duration']
            progress_s = track_progress / 1000
            duration_s = track_duration / 1000
            print(f"   Progress: {progress_s:>5.1f} / {duration_s:>5.1f} s")

    def on_group_update(group_info: dict) -> None:
        """Handle group updates."""
        print(f"Group: {group_info['group_id']}")
        if group_info.get('playback_state'):
            print(f"   State: {group_info['playback_state']}")

    def on_controller_state_update(state: dict) -> None:
        """Handle controller state updates."""
        print(f"Controller: Volume={state['volume']}%, Muted={state['muted']}")

    def on_event(message: str) -> None:
        """Handle general events."""
        print(f"Event: {message}")

    # Configure the client with callbacks
    config = SendspinAudioClientConfig(
        url="ws://localhost:8927/sendspin",  # Change to your server URL
        client_id="example-client",
        client_name="Example Player",
        static_delay_ms=0.0,  # Adjust if needed for your audio hardware
        audio_device=selected_device,  # Use AudioDevice instance
        on_metadata_update=on_metadata_update,
        on_group_update=on_group_update,
        on_controller_state_update=on_controller_state_update,
        on_event=on_event,
    )

    # Create the client
    client = SendspinAudioClient(config)

    # Optionally monitor timing metrics and state
    async def monitor_metrics():
        """Periodically print timing metrics and state."""
        while True:
            await asyncio.sleep(5.0)
            if client.is_connected:
                # Print timing metrics
                metrics = client.get_timing_metrics()
                if metrics:
                    print(
                        f"Metrics: position={metrics['playback_position_us']/1e6:.2f}s, buffered={metrics['buffered_audio_us']/1e6:.2f}s"
                    )

                # Query and print current state
                metadata = client.get_metadata()
                if metadata.get('title'):
                    print(f"Current: {metadata['title']} - {metadata['artist']}")

                # Get track progress
                track_progress, track_duration = client.get_track_progress()
                if track_duration:
                    # Convert from milliseconds to seconds and format
                    progress_s = (track_progress or 0) / 1000
                    duration_s = track_duration / 1000
                    print(f"Progress: {progress_s:>5.1f} / {duration_s:>5.1f} s")

                playback_state = client.get_playback_state()
                if playback_state:
                    print(f"Playback: {playback_state.value}")

                group_info = client.get_group_info()
                if group_info.get('group_id'):
                    print(f"Group ID: {group_info['group_id']}")

                # Show volume info
                controller_vol, controller_muted = client.get_controller_volume()
                if controller_vol is not None:
                    print(f"Controller Volume: {controller_vol}% {'(muted)' if controller_muted else ''}")

                player_vol, player_muted = client.get_player_volume()
                print(f"Player Volume: {player_vol}% {'(muted)' if player_muted else ''}")

                # Show supported commands
                commands = client.get_supported_commands()
                if commands:
                    print(f"Supported Commands: {', '.join(c.value for c in commands)}")

    # Start monitoring in background
    monitor_task = asyncio.create_task(monitor_metrics())

    try:
        print("Connecting to Sendspin server...")
        print("Press Ctrl+C to stop")

        # Simple reconnection loop
        try:
            while True:
                try:
                    await client.connect()
                    print("Connected! Playing audio...")

                    # Wait for disconnect
                    try:
                        await client.wait_for_disconnect()
                        print("Connection lost, reconnecting in 2 seconds...")
                        await asyncio.sleep(2.0)
                    except asyncio.CancelledError:
                        # Disconnect was requested (e.g., Ctrl+C)
                        break
                except (TimeoutError, OSError, ClientError) as e:
                    print(f"Connection error: {e}")
                    print("Retrying in 5 seconds...")
                    await asyncio.sleep(5.0)
                except Exception as e:
                    print(f"Unexpected error: {e}")
                    print("Retrying in 5 seconds...")
                    await asyncio.sleep(5.0)
        except KeyboardInterrupt:
            print("\nInterrupted by user")
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        print("Disconnecting...")
        await client.disconnect()
        print("Disconnected")


if __name__ == "__main__":
    asyncio.run(main())

