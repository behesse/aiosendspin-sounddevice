"""Tests for the SendspinAudioClient."""

import asyncio
import pytest
from aiohttp import ClientError
from aiosendspin_sounddevice import (
    AudioDevice,
    AudioDeviceManager,
    SendspinAudioClient,
    SendspinAudioClientConfig,
)


@pytest.mark.asyncio
async def test_client_initialization():
    """Test that the client can be initialized."""
    config = SendspinAudioClientConfig(
        url="ws://localhost:8927/sendspin",
        client_id="test-client",
        client_name="Test Client",
    )
    client = SendspinAudioClient(config)
    assert client is not None
    assert not client.is_connected


@pytest.mark.asyncio
async def test_client_auto_hostname():
    """Test that the client auto-generates hostname-based IDs."""
    config = SendspinAudioClientConfig(
        url="ws://localhost:8927/sendspin",
    )
    client = SendspinAudioClient(config)
    assert client is not None


@pytest.mark.asyncio
async def test_client_connection_failure():
    """Test that connection fails when server is unavailable."""
    config = SendspinAudioClientConfig(
        url="ws://localhost:9999/sendspin",
        client_id="test-client",
        client_name="Test Client",
    )
    client = SendspinAudioClient(config)

    # Connection should fail (server not available)
    with pytest.raises((TimeoutError, OSError, ClientError)):
        await asyncio.wait_for(client.connect(), timeout=2.0)


@pytest.mark.asyncio
async def test_client_timing_metrics():
    """Test that timing metrics can be retrieved."""
    config = SendspinAudioClientConfig(
        url="ws://localhost:8927/sendspin",
        client_id="test-client",
        client_name="Test Client",
    )
    client = SendspinAudioClient(config)

    # Should return None when not connected/playing
    metrics = client.get_timing_metrics()
    assert metrics is None


@pytest.mark.asyncio
async def test_client_volume_control():
    """Test volume control methods."""
    config = SendspinAudioClientConfig(
        url="ws://localhost:8927/sendspin",
        client_id="test-client",
        client_name="Test Client",
    )
    client = SendspinAudioClient(config)

    # Should not raise even when not connected
    client.set_volume(50, muted=False)
    client.set_volume(75, muted=True)


def test_audio_device_manager():
    """Test AudioDeviceManager."""
    manager = AudioDeviceManager()
    
    # Get devices
    devices = manager.get_devices()
    assert isinstance(devices, list)
    assert len(devices) > 0
    assert all(isinstance(d, AudioDevice) for d in devices)
    
    # Check that at least one device has output channels
    assert any(d.max_output_channels > 0 for d in devices)
    
    # Check default device
    default = manager.get_default_device()
    if default:
        assert isinstance(default, AudioDevice)
        assert default.is_default
    
    # Test refresh
    manager.refresh()
    devices_after_refresh = manager.get_devices()
    assert len(devices_after_refresh) == len(devices)


def test_audio_device_manager_find():
    """Test AudioDeviceManager find methods."""
    manager = AudioDeviceManager()
    devices = manager.get_devices()
    
    if not devices:
        pytest.skip("No audio devices available")
    
    # Find by index
    first_device = devices[0]
    found = manager.find_by_index(first_device.index)
    assert found is not None
    assert found.index == first_device.index
    assert found == first_device
    
    # Find by name (prefix)
    found_by_name = manager.find_by_name(first_device.name[:10])
    assert found_by_name is not None
    
    # Find by exact name
    found_exact = manager.find_by_name(first_device.name, exact=True)
    assert found_exact is not None
    assert found_exact.name == first_device.name
    
    # Find all by name
    all_matches = manager.find_all_by_name(first_device.name[:5])
    assert len(all_matches) > 0
    assert all(isinstance(d, AudioDevice) for d in all_matches)


def test_audio_device():
    """Test AudioDevice class."""
    device = AudioDevice(
        index=0,
        name="Test Device",
        max_output_channels=2,
        default_samplerate=44100.0,
        is_default=True,
    )
    
    assert device.index == 0
    assert device.name == "Test Device"
    assert device.max_output_channels == 2
    assert device.default_samplerate == 44100.0
    assert device.is_default is True
    
    # Test string representation
    assert "Test Device" in str(device)
    assert "default" in str(device)
    assert "index=0" in str(device)
    
    # Test equality
    device2 = AudioDevice(
        index=0,
        name="Different Name",
        max_output_channels=4,
        default_samplerate=48000.0,
        is_default=False,
    )
    assert device == device2  # Same index
    
    device3 = AudioDevice(
        index=1,
        name="Test Device",
        max_output_channels=2,
        default_samplerate=44100.0,
        is_default=False,
    )
    assert device != device3  # Different index


@pytest.mark.asyncio
async def test_client_with_audio_device():
    """Test client initialization with AudioDevice."""
    manager = AudioDeviceManager()
    devices = manager.get_devices()
    if not devices:
        pytest.skip("No audio devices available")
    
    # Use first available device
    device = devices[0]
    config = SendspinAudioClientConfig(
        url="ws://localhost:8080/sendspin",
        client_id="test-client",
        client_name="Test Client",
        audio_device=device,  # Pass AudioDevice instance
    )
    client = SendspinAudioClient(config)
    assert client is not None


if __name__ == "__main__":
    # Simple test runner for manual testing
    import sys

    print("Running basic tests...")
    print("Note: These tests require a Sendspin server to be running for full functionality.")
    print("Some tests may fail if no server is available, which is expected.")

    # Test AudioDeviceManager
    try:
        manager = AudioDeviceManager()
        devices = manager.get_devices()
        print(f"✓ AudioDeviceManager: Found {len(devices)} devices")
        default = manager.get_default_device()
        if default:
            print(f"✓ Default device: {default.name}")
    except Exception as e:
        print(f"✗ AudioDeviceManager: FAILED - {e}")
        sys.exit(1)

    # Test initialization
    try:
        config = SendspinAudioClientConfig(
            url="ws://localhost:8927/sendspin",
            client_id="test-client",
            client_name="Test Client",
        )
        client = SendspinAudioClient(config)
        print("✓ Client initialization: OK")
    except Exception as e:
        print(f"✗ Client initialization: FAILED - {e}")
        sys.exit(1)

    print("\nAll basic tests passed!")
    print("\nTo test with a real server:")
    print("1. Start a Sendspin server")
    print("2. Run: python -m pytest tests/test_client.py -v")
