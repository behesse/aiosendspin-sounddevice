"""Audio device management for Sendspin audio playback."""

from __future__ import annotations

import sounddevice


class AudioDevice:
    """Represents an audio output device."""

    def __init__(
        self,
        index: int,
        name: str,
        max_output_channels: int,
        default_samplerate: float,
        is_default: bool = False,
    ) -> None:
        """Initialize an audio device.

        Args:
            index: Device index as used by sounddevice.
            name: Device name.
            max_output_channels: Maximum number of output channels.
            default_samplerate: Default sample rate.
            is_default: Whether this is the default output device.

        """
        self.index = index
        """Device index as used by sounddevice."""
        self.name = name
        """Device name."""
        self.max_output_channels = max_output_channels
        """Maximum number of output channels."""
        self.default_samplerate = default_samplerate
        """Default sample rate."""
        self.is_default = is_default
        """Whether this is the default output device."""

    def __str__(self) -> str:
        """Return string representation of the device."""
        default_marker = " (default)" if self.is_default else ""
        return (
            f"AudioDevice(index={self.index}, name='{self.name}', "
            f"channels={self.max_output_channels}, samplerate={self.default_samplerate}{default_marker})"
        )

    def __repr__(self) -> str:
        """Representation of the device."""
        return self.__str__()

    def __eq__(self, other: object) -> bool:
        """Check equality based on device index."""
        if not isinstance(other, AudioDevice):
            return False
        return self.index == other.index

    def __hash__(self) -> int:
        """Hash based on device index."""
        return hash(self.index)


class AudioDeviceManager:
    """Manages audio device discovery and selection."""

    def __init__(self) -> None:
        """Initialize the audio device manager."""
        self._devices: list[AudioDevice] | None = None
        self._default_device: AudioDevice | None = None

    def refresh(self) -> None:
        """Refresh the list of available audio devices."""
        devices = sounddevice.query_devices()
        default_output_index = sounddevice.default.device[1]  # Output device index

        self._devices = []
        for i, dev in enumerate(devices):
            if dev["max_output_channels"] > 0:  # Only include output devices
                is_default = i == default_output_index
                audio_device = AudioDevice(
                    index=i,
                    name=dev["name"],
                    max_output_channels=dev["max_output_channels"],
                    default_samplerate=dev["default_samplerate"],
                    is_default=is_default,
                )
                self._devices.append(audio_device)
                if is_default:
                    self._default_device = audio_device

    def get_devices(self) -> list[AudioDevice]:
        """Get all available audio output devices.

        Returns:
            List of AudioDevice instances representing available output devices.

        """
        if self._devices is None:
            self.refresh()
        if self._devices is None:
            raise RuntimeError("Audio devices have not been initialized")
        return self._devices.copy()

    def get_default_device(self) -> AudioDevice | None:
        """Get the default audio output device.

        Returns:
            AudioDevice instance for the default device, or None if no default.

        """
        if self._devices is None:
            self.refresh()
        return self._default_device

    def find_by_index(self, index: int) -> AudioDevice | None:
        """Find an audio device by its index.

        Args:
            index: Device index to search for.

        Returns:
            AudioDevice instance if found, None otherwise.

        """
        if self._devices is None:
            self.refresh()
        if self._devices is None:
            raise RuntimeError("Audio devices have not been initialized")
        for device in self._devices:
            if device.index == index:
                return device
        return None

    def find_by_name(self, name: str, exact: bool = False) -> AudioDevice | None:
        """Find an audio device by name.

        Args:
            name: Device name or name prefix to search for.
            exact: If True, match exact name. If False, match name prefix.

        Returns:
            AudioDevice instance if found, None otherwise.

        """
        if self._devices is None:
            self.refresh()
        if self._devices is None:
            raise RuntimeError("Audio devices have not been initialized")
        for device in self._devices:
            if exact:
                if device.name == name:
                    return device
            elif device.name.startswith(name):
                return device
        return None

    def find_all_by_name(self, name: str, exact: bool = False) -> list[AudioDevice]:
        """Find all audio devices matching a name.

        Args:
            name: Device name or name prefix to search for.
            exact: If True, match exact name. If False, match name prefix.

        Returns:
            List of AudioDevice instances matching the name.

        """
        if self._devices is None:
            self.refresh()
        if self._devices is None:
            raise RuntimeError("Failed to initialize audio devices")
        matches = []
        for device in self._devices:
            if exact:
                if device.name == name:
                    matches.append(device)
            elif device.name.startswith(name):
                matches.append(device)
        return matches

    @staticmethod
    def list_audio_devices() -> list[AudioDevice]:
        """List all available audio output devices.

        Returns:
            List of AudioDevice instances representing available output devices.

        """
        manager = AudioDeviceManager()
        return manager.get_devices()
