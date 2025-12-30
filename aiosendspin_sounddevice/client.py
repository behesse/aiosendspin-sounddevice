"""Main client class for programmatic Sendspin audio playback."""

from __future__ import annotations

import asyncio
import logging
import platform
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sounddevice
from aiosendspin.client import PCMFormat, SendspinClient
from aiosendspin.models.core import (
    DeviceInfo,
    GroupUpdateServerPayload,
    ServerCommandPayload,
    ServerStatePayload,
    StreamStartMessage,
)
from aiosendspin.models.player import (
    ClientHelloPlayerSupport,
    PlayerCommandPayload,
    SupportedAudioFormat,
)
from aiosendspin.models.types import (
    AudioCodec,
    MediaCommand,
    PlaybackStateType,
    PlayerCommand,
    PlayerStateType,
    Roles,
    UndefinedField,
)

from aiosendspin_sounddevice.audio import AudioPlayer
from aiosendspin_sounddevice.audio_device import AudioDevice

if TYPE_CHECKING:
    from aiosendspin.models.metadata import SessionUpdateMetadata

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """Holds state mirrored from the server for CLI presentation."""

    playback_state: PlaybackStateType | None = None
    supported_commands: set[MediaCommand] = field(default_factory=set)
    volume: int | None = None
    muted: bool | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    track_progress: int | None = None
    track_duration: int | None = None
    progress_updated_at: float = 0.0  # time.monotonic() when progress was updated
    player_volume: int = 100
    player_muted: bool = False
    group_id: str | None = None

    def update_metadata(self, metadata: SessionUpdateMetadata) -> bool:
        """Merge new metadata into the state and report if anything changed."""
        changed = False
        for attr in ("title", "artist", "album"):
            value = getattr(metadata, attr)
            if isinstance(value, UndefinedField):
                continue
            if getattr(self, attr) != value:
                setattr(self, attr, value)
                changed = True

        # Update progress fields from nested progress object
        if not isinstance(metadata.progress, UndefinedField):
            if metadata.progress is None:
                # Clear progress fields
                if self.track_progress is not None or self.track_duration is not None:
                    self.track_progress = None
                    self.track_duration = None
                    self.progress_updated_at = 0.0
                    changed = True
            else:
                # Update from nested progress object
                if self.track_progress != metadata.progress.track_progress:
                    self.track_progress = metadata.progress.track_progress
                    self.progress_updated_at = time.monotonic()
                    changed = True
                if self.track_duration != metadata.progress.track_duration:
                    self.track_duration = metadata.progress.track_duration
                    changed = True

        return changed

    def describe(self) -> str:
        """Return a human-friendly description of the current state."""
        lines: list[str] = []
        if self.title:
            lines.append(f"Now playing: {self.title}")
        if self.artist:
            lines.append(f"Artist: {self.artist}")
        if self.album:
            lines.append(f"Album: {self.album}")
        if self.track_duration:
            progress_s = (self.track_progress or 0) / 1000
            duration_s = self.track_duration / 1000
            lines.append(f"Progress: {progress_s:>5.1f} / {duration_s:>5.1f} s")
        if self.volume is not None:
            vol_line = f"Volume: {self.volume}%"
            if self.muted:
                vol_line += " (muted)"
            lines.append(vol_line)
        if self.playback_state is not None:
            lines.append(f"State: {self.playback_state.value}")
        return "\n".join(lines)


def get_device_info() -> DeviceInfo:  # noqa: C901
    """Get device information for the client hello message."""
    # Get OS/platform information
    system = platform.system()
    product_name = f"{system}"

    # Try to get more specific product info
    if system == "Linux":
        # Try reading /etc/os-release for distribution info
        try:
            os_release = Path("/etc/os-release")
            if os_release.exists():
                with os_release.open() as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            product_name = line.split("=", 1)[1].strip().strip('"')
                            break
        except (OSError, IndexError):
            pass
    elif system == "Darwin":
        mac_version = platform.mac_ver()[0]
        product_name = f"macOS {mac_version}" if mac_version else "macOS"
    elif system == "Windows":
        try:
            win_ver = platform.win32_ver()
            # Check build number to distinguish Windows 11 (build 22000+) from Windows 10
            if win_ver[0] == "10" and win_ver[1] and int(win_ver[1].split(".")[2]) >= 22000:  # noqa: SIM108
                product_name = "Windows 11"
            else:
                product_name = f"Windows {win_ver[0]}"
        except (ValueError, IndexError, AttributeError):
            product_name = f"Windows {platform.release()}"

    # Get software version
    try:
        software_version = f"aiosendspin {version('aiosendspin')}"
    except Exception:  # noqa: BLE001
        software_version = "aiosendspin (unknown version)"

    return DeviceInfo(
        product_name=product_name,
        manufacturer=None,  # Could add manufacturer detection if needed
        software_version=software_version,
    )


def resolve_audio_device(device: AudioDevice | str | int | None) -> int | None:  # noqa: C901
    """Resolve audio device to a device index.

    Args:
        device: AudioDevice instance, device index (int), name prefix (str), or None for default.

    Returns:
        Device index if valid, None for default device.

    Raises:
        ValueError: If device is invalid or not found.

    """
    if device is None:
        return None

    # If it's already an AudioDevice, use its index
    if isinstance(device, AudioDevice):
        return device.index

    devices = sounddevice.query_devices()

    # If numeric, treat as device index
    if isinstance(device, int):
        device_id = device
    elif isinstance(device, str) and device.isnumeric():
        device_id = int(device)
    else:
        device_id = None

    if device_id is not None:
        if 0 <= device_id < len(devices):
            if devices[device_id]["max_output_channels"] > 0:
                return device_id
            raise ValueError(f"Device {device_id} has no output channels")
        raise ValueError(f"Device index {device_id} out of range (0-{len(devices) - 1})")

    # Otherwise, find first output device whose name starts with the prefix
    if isinstance(device, str):
        for i, dev in enumerate(devices):
            if dev["max_output_channels"] > 0 and dev["name"].startswith(device):
                return i

        raise ValueError(f"No audio output device found matching '{device}'")

    raise ValueError(f"Invalid device specification: {device}")


class AudioStreamHandler:
    """Manages audio playback state and stream lifecycle."""

    def __init__(self, client: SendspinClient, audio_device: int | None = None) -> None:
        """Initialize the audio stream handler.

        Args:
            client: The Sendspin client instance.
            audio_device: Audio device ID to use. None for default device.

        """
        self._client = client
        self._audio_device = audio_device
        self.audio_player: AudioPlayer | None = None
        self._current_format: PCMFormat | None = None

    def on_audio_chunk(self, server_timestamp_us: int, audio_data: bytes, fmt: PCMFormat) -> None:
        """Handle incoming audio chunks."""
        # Initialize or reconfigure audio player if format changed
        if self.audio_player is None or self._current_format != fmt:
            if self.audio_player is not None:
                self.audio_player.clear()

            loop = asyncio.get_running_loop()
            self.audio_player = AudioPlayer(
                loop, self._client.compute_play_time, self._client.compute_server_time
            )
            self.audio_player.set_format(fmt, device=self._audio_device)
            self._current_format = fmt

        # Submit audio chunk - AudioPlayer handles timing
        if self.audio_player is not None:
            self.audio_player.submit(server_timestamp_us, audio_data)

    def on_stream_start(
        self, _message: StreamStartMessage, print_event: Callable[[str], None]
    ) -> None:
        """Handle stream start by clearing stale audio chunks."""
        if self.audio_player is not None:
            self.audio_player.clear()
            logger.debug("Cleared audio queue on stream start")
        print_event("Stream started")

    def on_stream_end(self, roles: list[Roles] | None, print_event: Callable[[str], None]) -> None:
        """Handle stream end by clearing audio queue to prevent desync on resume."""
        # For the CLI player, we only care about the player role
        if (roles is None or Roles.PLAYER in roles) and self.audio_player is not None:
            self.audio_player.clear()
            logger.debug("Cleared audio queue on stream end")
            print_event("Stream ended")

    def on_stream_clear(self, roles: list[Roles] | None) -> None:
        """Handle stream clear by clearing audio queue (e.g., for seek operations)."""
        # For the CLI player, we only care about the player role
        if (roles is None or Roles.PLAYER in roles) and self.audio_player is not None:
            self.audio_player.clear()
            logger.debug("Cleared audio queue on stream clear")

    def clear_queue(self) -> None:
        """Clear the audio queue to prevent desync."""
        if self.audio_player is not None:
            self.audio_player.clear()

    async def cleanup(self) -> None:
        """Stop audio player and clear resources."""
        if self.audio_player is not None:
            await self.audio_player.stop()
            self.audio_player = None


@dataclass
class SendspinAudioClientConfig:
    """Configuration for the Sendspin audio client."""

    url: str
    """WebSocket URL of the Sendspin server."""
    client_id: str | None = None
    """Unique client identifier. If None, auto-generated from hostname."""
    client_name: str | None = None
    """Friendly client name. If None, uses hostname."""
    static_delay_ms: float = 0.0
    """Static delay compensation in milliseconds."""
    audio_device: AudioDevice | str | int | None = None
    """Audio device. Can be AudioDevice instance, device index (int), name prefix (str), or None for default device."""
    on_metadata_update: Callable[[dict[str, Any]], None] | None = None
    """Optional callback for metadata updates. Receives dict with title, artist, album, progress, duration."""
    on_group_update: Callable[[dict[str, Any]], None] | None = None
    """Optional callback for group updates. Receives dict with group_id, group_name, playback_state."""
    on_controller_state_update: Callable[[dict[str, Any]], None] | None = None
    """Optional callback for controller state updates. Receives dict with volume, muted, supported_commands."""
    on_event: Callable[[str], None] | None = None
    """Optional callback for general events (stream started, stream ended, etc.)."""


class SendspinAudioClient:
    """Programmatic client for connecting to Sendspin servers and playing audio.

    This class manages the connection to a Sendspin server and handles audio playback
    through sounddevice, including all buffering, time synchronization, and stream management.
    The user is responsible for handling reconnection logic.

    Example::

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
                # Wait for disconnect
                await client.wait_for_disconnect()
            except KeyboardInterrupt:
                pass
            finally:
                await client.disconnect()

        asyncio.run(main())

    """

    def __init__(self, config: SendspinAudioClientConfig) -> None:
        """Initialize the Sendspin audio client.

        Args:
            config: Configuration for the client.

        """
        self._config = config
        self._client: SendspinClient | None = None
        self._audio_handler: AudioStreamHandler | None = None
        self._connected = False
        self._disconnect_event: asyncio.Event | None = None
        self._state = AppState()

        # Get hostname for defaults if needed
        client_id = config.client_id
        client_name = config.client_name
        if client_id is None or client_name is None:
            hostname = socket.gethostname()
            if not hostname:
                raise ValueError(
                    "Unable to determine hostname. Please specify client_id and/or client_name"
                )
            # Auto-generate client ID and name from hostname
            if client_id is None:
                client_id = f"sendspin-cli-{hostname}"
            if client_name is None:
                client_name = hostname

        # Resolve audio device if specified
        audio_device = None
        if config.audio_device is not None:
            try:
                audio_device = resolve_audio_device(config.audio_device)
                if audio_device is not None:
                    device_name = sounddevice.query_devices(audio_device)["name"]
                    logger.debug("Using audio device %d: %s", audio_device, device_name)
            except ValueError:
                logger.exception("Audio device error: %s")
                raise

        # Create Sendspin client
        self._client = SendspinClient(
            client_id=client_id,
            client_name=client_name,
            roles=[Roles.CONTROLLER, Roles.PLAYER, Roles.METADATA],
            device_info=get_device_info(),
            player_support=ClientHelloPlayerSupport(
                supported_formats=[
                    SupportedAudioFormat(
                        codec=AudioCodec.PCM, channels=2, sample_rate=44_100, bit_depth=16
                    ),
                    SupportedAudioFormat(
                        codec=AudioCodec.PCM, channels=1, sample_rate=44_100, bit_depth=16
                    ),
                ],
                buffer_capacity=32_000_000,
                supported_commands=[PlayerCommand.VOLUME, PlayerCommand.MUTE],
            ),
            static_delay_ms=config.static_delay_ms,
        )

        # Create audio handler
        self._audio_handler = AudioStreamHandler(self._client, audio_device=audio_device)

        # Setup event listeners - MUST be done before connecting
        self._setup_listeners()

    def _setup_listeners(self) -> None:
        """Set up client event listeners."""
        if self._client is None:
            raise RuntimeError("Client not initialized")
        if self._audio_handler is None:
            raise RuntimeError("Audio handler not initialized")

        # Capture references for use in lambdas (type narrowing)
        client = self._client
        audio_handler = self._audio_handler

        # Set up all listeners
        client.set_metadata_listener(self._handle_metadata_update)
        client.set_group_update_listener(self._handle_group_update)
        client.set_controller_state_listener(self._handle_controller_state)
        client.set_stream_start_listener(
            lambda msg: audio_handler.on_stream_start(msg, self._print_event)
        )
        client.set_stream_end_listener(
            lambda roles: audio_handler.on_stream_end(roles, self._print_event)
        )
        client.set_stream_clear_listener(audio_handler.on_stream_clear)
        client.set_audio_chunk_listener(audio_handler.on_audio_chunk)
        client.set_server_command_listener(self._handle_server_command)

    def _print_event(self, message: str) -> None:
        """Print an event message."""
        logger.debug("Event: %s", message)
        if self._config.on_event is not None:
            try:
                self._config.on_event(message)
            except Exception:
                logger.exception("Error in on_event callback")

    async def _handle_metadata_update(self, payload: ServerStatePayload) -> None:
        """Handle server/state messages with metadata."""
        if payload.metadata is not None and self._state.update_metadata(payload.metadata):
            # Notify callback if registered
            if self._config.on_metadata_update is not None:
                try:
                    self._config.on_metadata_update(
                        {
                            "title": self._state.title,
                            "artist": self._state.artist,
                            "album": self._state.album,
                            "track_progress": self._state.track_progress,
                            "track_duration": self._state.track_duration,
                        }
                    )
                except Exception:
                    logger.exception("Error in on_metadata_update callback")
            self._print_event(self._state.describe())

    async def _handle_group_update(self, payload: GroupUpdateServerPayload) -> None:
        """Handle group update messages."""
        # Only clear metadata when actually switching to a different group
        group_changed = payload.group_id is not None and payload.group_id != self._state.group_id
        if group_changed:
            self._state.group_id = payload.group_id
            self._state.title = None
            self._state.artist = None
            self._state.album = None
            self._state.track_progress = None
            self._state.track_duration = None
            self._state.progress_updated_at = 0.0
            self._print_event(f"Group ID: {payload.group_id}")

        if payload.group_name:
            self._print_event(f"Group name: {payload.group_name}")

        if payload.playback_state:
            # When leaving PLAYING, capture interpolated progress so display doesn't jump
            if (
                self._state.playback_state == PlaybackStateType.PLAYING
                and payload.playback_state != PlaybackStateType.PLAYING
                and self._state.progress_updated_at > 0
                and self._state.track_duration
            ):
                elapsed_ms = (time.monotonic() - self._state.progress_updated_at) * 1000
                interpolated = (self._state.track_progress or 0) + int(elapsed_ms)
                self._state.track_progress = min(self._state.track_duration, interpolated)
                # Reset timestamp so resume starts fresh from captured position
                self._state.progress_updated_at = time.monotonic()

            self._state.playback_state = payload.playback_state
            self._print_event(f"Playback state: {payload.playback_state.value}")

        # Notify callback if registered (call once with all current info)
        if self._config.on_group_update is not None and (
            group_changed or payload.group_name or payload.playback_state
        ):
            try:
                self._config.on_group_update(
                    {
                        "group_id": self._state.group_id,
                        "group_name": payload.group_name if payload.group_name else None,
                        "playback_state": payload.playback_state.value
                        if payload.playback_state
                        else (
                            self._state.playback_state.value if self._state.playback_state else None
                        ),
                    }
                )
            except Exception:
                logger.exception("Error in on_group_update callback")

    async def _handle_controller_state(self, payload: ServerStatePayload) -> None:
        """Handle server/state messages with controller state."""
        if payload.controller:
            controller = payload.controller
            self._state.supported_commands = set(controller.supported_commands)

            volume_changed = controller.volume != self._state.volume
            mute_changed = controller.muted != self._state.muted

            if volume_changed:
                self._state.volume = controller.volume
                self._print_event(f"Volume: {controller.volume}%")
            if mute_changed:
                self._state.muted = controller.muted
                self._print_event("Muted" if controller.muted else "Unmuted")

            # Notify callback if registered
            if self._config.on_controller_state_update is not None and (
                volume_changed or mute_changed
            ):
                try:
                    self._config.on_controller_state_update(
                        {
                            "volume": self._state.volume,
                            "muted": self._state.muted,
                            "supported_commands": list(self._state.supported_commands),
                        }
                    )
                except Exception:
                    logger.exception("Error in on_controller_state_update callback")

    async def _handle_server_command(self, payload: ServerCommandPayload) -> None:
        """Handle server/command messages for player volume/mute control."""
        if payload.player is None:
            return

        player_cmd: PlayerCommandPayload = payload.player
        audio_handler = self._audio_handler

        if player_cmd.command == PlayerCommand.VOLUME and player_cmd.volume is not None:
            self._state.player_volume = player_cmd.volume
            if audio_handler.audio_player is not None:
                audio_handler.audio_player.set_volume(
                    self._state.player_volume, muted=self._state.player_muted
                )
            self._print_event(f"Server set player volume: {player_cmd.volume}%")
        elif player_cmd.command == PlayerCommand.MUTE and player_cmd.mute is not None:
            self._state.player_muted = player_cmd.mute
            if audio_handler.audio_player is not None:
                audio_handler.audio_player.set_volume(
                    self._state.player_volume, muted=self._state.player_muted
                )
            self._print_event("Server muted player" if player_cmd.mute else "Server unmuted player")

        # Send state update back to server per spec
        if self._client is not None:
            await self._client.send_player_state(
                state=PlayerStateType.SYNCHRONIZED,
                volume=self._state.player_volume,
                muted=self._state.player_muted,
            )

    async def connect(self) -> None:
        """Connect to the Sendspin server.

        This is a one-shot connection. The user is responsible for handling
        reconnection if the connection is lost.

        Raises:
            TimeoutError: If connection times out.
            OSError: If connection fails (e.g., host unreachable).
            ClientError: If connection fails due to HTTP/WebSocket error.

        """
        if self._client is None:
            raise RuntimeError("Client not initialized")

        if self._connected:
            logger.warning("Already connected")
            return

        # Note: Library does not configure logging - application should configure it

        logger.debug("Connecting to %s", self._config.url)
        await self._client.connect(self._config.url)
        logger.debug("Connected to %s", self._config.url)
        self._connected = True

        # Set up disconnect listener
        self._disconnect_event = asyncio.Event()
        self._client.set_disconnect_listener(partial(asyncio.Event.set, self._disconnect_event))

    async def disconnect(self) -> None:
        """Disconnect from the server and cleanup resources."""
        if not self._connected:
            return

        # Signal disconnect event so wait_for_disconnect() completes
        if self._disconnect_event is not None:
            self._disconnect_event.set()

        # Cleanup audio
        if self._audio_handler is not None:
            await self._audio_handler.cleanup()

        # Disconnect client
        if self._client is not None:
            await self._client.disconnect()

        self._connected = False
        self._disconnect_event = None
        logger.debug("Disconnected")

    async def wait_for_disconnect(self) -> None:
        """Wait for the connection to be lost.

        This will block until the connection is lost or the client is disconnected.

        Raises:
            RuntimeError: If not connected.
            asyncio.CancelledError: If the wait is cancelled (e.g., during shutdown).

        """
        if not self._connected or self._disconnect_event is None:
            raise RuntimeError("Not connected")
        try:
            await self._disconnect_event.wait()
            self._connected = False
        except asyncio.CancelledError:
            # Re-raise cancellation so caller can handle it
            self._connected = False
            raise

    def get_timing_metrics(self) -> dict[str, float] | None:
        """Get current timing metrics from the audio player.

        Returns:
            Dictionary with timing metrics, or None if not playing.

        """
        if self._audio_handler is None or self._audio_handler.audio_player is None:
            return None
        return self._audio_handler.audio_player.get_timing_metrics()

    def set_volume(self, volume: int, *, muted: bool = False) -> None:
        """Set the player volume and mute state.

        Args:
            volume: Volume level 0-100.
            muted: Whether audio is muted.

        """
        if self._audio_handler is None or self._audio_handler.audio_player is None:
            logger.warning("Audio player not initialized")
            return
        self._state.player_volume = volume
        self._state.player_muted = muted
        self._audio_handler.audio_player.set_volume(volume, muted=muted)

    def get_metadata(self) -> dict[str, Any]:
        """Get current metadata (title, artist, album, progress).

        Returns:
            Dictionary with metadata fields: title, artist, album, track_progress, track_duration.
            Values may be None if not available.

        """
        return {
            "title": self._state.title,
            "artist": self._state.artist,
            "album": self._state.album,
            "track_progress": self._state.track_progress,
            "track_duration": self._state.track_duration,
        }

    def get_track_progress(self) -> tuple[int | None, int | None]:
        """Get current track progress and duration.

        Returns:
            Tuple of (track_progress_ms: int | None, track_duration_ms: int | None).
            Values are in milliseconds.
            Progress is interpolated if currently playing.

        """
        progress_ms = self._state.track_progress or 0
        duration_ms = self._state.track_duration or 0

        # Interpolate progress if playing
        if (
            self._state.playback_state == PlaybackStateType.PLAYING
            and self._state.progress_updated_at > 0
            and duration_ms > 0
        ):
            elapsed_ms = (time.monotonic() - self._state.progress_updated_at) * 1000
            progress_ms = min(duration_ms, progress_ms + int(elapsed_ms))

        return progress_ms if self._state.track_progress is not None else None, (
            duration_ms if self._state.track_duration is not None else None
        )

    def get_playback_state(self) -> PlaybackStateType | None:
        """Get current playback state.

        Returns:
            Current playback state (PLAYING, PAUSED, STOPPED, etc.) or None if unknown.

        """
        return self._state.playback_state

    def get_controller_volume(self) -> tuple[int | None, bool | None]:
        """Get controller volume and mute state.

        Returns:
            Tuple of (volume: int | None, muted: bool | None).

        """
        return self._state.volume, self._state.muted

    def get_player_volume(self) -> tuple[int, bool]:
        """Get player volume and mute state.

        Returns:
            Tuple of (volume: int, muted: bool).

        """
        return self._state.player_volume, self._state.player_muted

    def get_group_info(self) -> dict[str, Any]:
        """Get current group information.

        Returns:
            Dictionary with group_id. Note: group_name is not stored in state.

        """
        return {
            "group_id": self._state.group_id,
        }

    def get_supported_commands(self) -> set[MediaCommand]:
        """Get supported media commands from the server.

        Returns:
            Set of supported MediaCommand enum values.

        """
        return self._state.supported_commands.copy()

    def describe_state(self) -> str:
        """Get a human-readable description of the current state.

        Returns:
            Formatted string describing the current state.

        """
        return self._state.describe()

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._connected

    async def send_media_command(self, command: MediaCommand) -> None:
        """Send a media command with validation.

        Args:
            command: The media command to send.

        """
        if command not in self._state.supported_commands:
            self._print_event(f"Server does not support {command.value}")
            return
        if self._client is None:
            raise RuntimeError("Not connected")
        await self._client.send_group_command(command)

    async def toggle_play_pause(self) -> None:
        """Toggle between play and pause based on current playback state."""
        if self._state.playback_state == PlaybackStateType.PLAYING:
            await self.send_media_command(MediaCommand.PAUSE)
        else:
            await self.send_media_command(MediaCommand.PLAY)

    async def play(self) -> None:
        """Send play command to the server."""
        await self.send_media_command(MediaCommand.PLAY)

    async def pause(self) -> None:
        """Send pause command to the server."""
        await self.send_media_command(MediaCommand.PAUSE)

    async def next_track(self) -> None:
        """Send next track command to the server."""
        await self.send_media_command(MediaCommand.NEXT)

    async def previous_track(self) -> None:
        """Send previous track command to the server."""
        await self.send_media_command(MediaCommand.PREVIOUS)

    async def switch_group(self) -> None:
        """Send switch group command to the server."""
        await self.send_media_command(MediaCommand.SWITCH)
