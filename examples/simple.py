#!/usr/bin/env python3

import asyncio
from aiosendspin_sounddevice import SendspinAudioClient, SendspinAudioClientConfig


async def main():
    """Connect to server and play audio."""
    config = SendspinAudioClientConfig(
        url="ws://localhost:8927/sendspin",
        client_id="simple-client",
        client_name="Simple Player",
    )
    
    client = SendspinAudioClient(config)
    
    try:
        await client.connect()
        print("Connected! Playing audio... Press Ctrl+C to stop")
        try:
            await client.wait_for_disconnect()
        except asyncio.CancelledError:
            # Disconnect was requested (e.g., Ctrl+C)
            pass
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

