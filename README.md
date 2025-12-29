# aiosendspin-sounddevice

> **⚠️ Work in Progress**  
> This library is currently under active development and not yet available on PyPI. API might change heavily. It's also not versioned yet.

Python library for programmatic audio playback from Sendspin servers. Provides a clean API for connecting to Sendspin servers, receiving synchronized audio streams, and playing them through local audio devices with precise time synchronization, buffering, and drift correction.

## Installation

> **Note:** This package is not yet available on PyPI. Install from source:

```bash
git clone <repository-url>
cd aiosendspin-sounddevice
pip install .
```

## Quick Start

```python
import asyncio
from aiosendspin_sounddevice import SendspinAudioClient, SendspinAudioClientConfig

async def main():
    config = SendspinAudioClientConfig(
        url="ws://192.168.1.100:8080/sendspin",
        client_id="my-client",
        client_name="My Player",
    )
    
    client = SendspinAudioClient(config)
    
    try:
        await client.connect()
        print("Connected! Playing audio... Press Ctrl+C to stop")
        await client.wait_for_disconnect()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

See `examples/simple.py` for a minimal working example, or `examples/comprehensive.py` for all features.

## Implementation Details

The library is organized into several key components:

### Core Components

- **`SendspinAudioClient`** (`client.py`): Main API class providing programmatic access to Sendspin servers. Handles connection management, state tracking, event listeners, and provides query methods for metadata, playback state, volume, and timing metrics.

- **`AudioPlayer`** (`audio.py`): Low-level audio playback engine with DAC-level timing precision. Implements:
  - Time-synchronized playback using server timestamps and client clock synchronization
  - Intelligent buffering with configurable thresholds to absorb network jitter
  - Sync error correction via playback speed adjustment (±4% range)
  - Gap and overlap detection for seamless audio continuity
  - Playback state machine (initializing, waiting, playing, re-anchoring)

- **`AudioStreamHandler`** (`client.py`): Manages audio stream lifecycle and format changes. Handles stream start/end/clear events and audio chunk routing to the AudioPlayer.

- **`AudioDeviceManager`** (`audio_device.py`): Object-oriented audio device discovery and selection. Provides methods to list, find, and select audio output devices.

- **`AppState`** (`client.py`): Internal state management mirroring server state (playback state, metadata, volume, group info) with client-side progress interpolation.

### Architecture

The library follows an event-driven architecture:
- Server events (metadata updates, group changes, controller state) trigger internal handlers
- Optional user-defined callbacks can be registered for reactive programming
- State can be queried actively via public API methods
- Audio chunks are processed asynchronously with precise timing

All core audio playback, synchronization, and state management logic is based on the [sendspin-cli](https://github.com/Sendspin/sendspin-cli) reference implementation.

## Limitations

See `FEATURE_COMPARISON.md` for current limitations in comparison to [sendspin-cli](https://github.com/Sendspin/sendspin-cli).
Major missing features are the controller role and service discovery.

## License

Apache-2.0

## Credits

Based on the [sendspin-cli](https://github.com/Sendspin/sendspin-cli) by the Sendspin Protocol authors.

