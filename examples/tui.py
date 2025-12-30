#!/usr/bin/env python3
"""TUI example for aiosendspin-sounddevice using Rich.

This example demonstrates building a terminal UI similar to sendspin-cli
using the aiosendspin-sounddevice library.

Requirements:
    pip install rich readchar
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

try:
    import readchar
    from rich.console import Console, ConsoleOptions, RenderResult
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError as e:
    print(f"Error: Missing required dependencies for TUI example: {e}")
    print("Install with: pip install rich readchar")
    sys.exit(1)

from aiosendspin.models.types import PlaybackStateType

from aiosendspin_sounddevice import (
    AudioDeviceManager,
    DiscoveredServer,
    SendspinAudioClient,
    SendspinAudioClientConfig,
    ServiceDiscovery,
)

if TYPE_CHECKING:
    from aiosendspin_sounddevice.client import SendspinAudioClient

logger = logging.getLogger(__name__)

# Duration in seconds to highlight a pressed shortcut
SHORTCUT_HIGHLIGHT_DURATION = 0.15


@dataclass
class UIState:
    """Holds state for the UI display."""

    # Connection
    server_url: str | None = None
    connected: bool = False
    status_message: str = "Initializing..."
    group_name: str | None = None

    # Server selector
    show_server_selector: bool = False
    available_servers: list[DiscoveredServer] = field(default_factory=list)
    selected_server_index: int = 0

    # Playback
    playback_state: PlaybackStateType | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    track_progress_ms: int | None = None
    track_duration_ms: int | None = None
    progress_updated_at: float = 0.0  # time.monotonic() when progress was updated

    # Volume
    volume: int | None = None
    muted: bool = False
    player_volume: int = 100
    player_muted: bool = False

    # Delay
    delay_ms: float = 0.0

    # Shortcut highlight
    highlighted_shortcut: str | None = None
    highlight_time: float = 0.0


class _RefreshableLayout:
    """A renderable that rebuilds on each render cycle."""

    def __init__(self, ui: SendspinTUI) -> None:
        self._ui = ui

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Rebuild and yield the layout on each render."""
        yield self._ui._build_layout()  # noqa: SLF001


class SendspinTUI:
    """Rich-based terminal UI for Sendspin client."""

    def __init__(self) -> None:
        """Initialize the UI."""
        self._console = Console()
        self._state = UIState()
        self._live: Live | None = None
        self._running = False

    @property
    def state(self) -> UIState:
        """Get the UI state for external updates."""
        return self._state

    def _format_time(self, ms: int | None) -> str:
        """Format milliseconds as MM:SS."""
        if ms is None:
            return "--:--"
        seconds = ms // 1000
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def _is_highlighted(self, shortcut: str) -> bool:
        """Check if a shortcut should be highlighted."""
        if self._state.highlighted_shortcut != shortcut:
            return False
        elapsed = time.monotonic() - self._state.highlight_time
        return elapsed < SHORTCUT_HIGHLIGHT_DURATION

    def _shortcut_style(self, shortcut: str) -> str:
        """Get the style for a shortcut key."""
        return "bold yellow reverse" if self._is_highlighted(shortcut) else "bold cyan"

    def highlight_shortcut(self, shortcut: str) -> None:
        """Highlight a shortcut temporarily."""
        self._state.highlighted_shortcut = shortcut
        self._state.highlight_time = time.monotonic()
        self.refresh()

    def _build_now_playing_panel(self, *, expand: bool = False) -> Panel:
        """Build the now playing panel."""
        # Show prompt when nothing is playing (5 lines total)
        if not self._state.title:
            content = Table.grid()
            content.add_column()
            content.add_row("")
            line1 = Text()
            line1.append("Press ", style="dim")
            line1.append("<space>", style="bold cyan")
            line1.append(" to start playing", style="dim")
            content.add_row(line1)
            line2 = Text()
            line2.append("Press ", style="dim")
            line2.append("g", style="bold cyan")
            line2.append(" to join an existing session", style="dim")
            content.add_row(line2)
            line3 = Text()
            line3.append("Press ", style="dim")
            line3.append("[", style="bold cyan")
            line3.append(" and ", style="dim")
            line3.append("]", style="bold cyan")
            line3.append(" to adjust audio delay", style="dim")
            content.add_row(line3)
            content.add_row("")
            return Panel(content, title="Now Playing", border_style="blue", expand=expand)

        # Info grid with label/value columns
        info = Table.grid(padding=(0, 1))
        info.add_column(style="dim", width=8)
        info.add_column()

        info.add_row("Title:", Text(self._state.title, style="bold white"))
        info.add_row("Artist:", Text(self._state.artist or "Unknown artist", style="cyan"))
        info.add_row("Album:", Text(self._state.album or "Unknown album", style="dim"))

        # Vertical container for info + shortcuts (5 lines total)
        content = Table.grid()
        content.add_column()
        content.add_row(info)
        content.add_row("")  # Line 4: spacing

        # Line 5: playback shortcuts (always show when track is loaded)
        space_label = "pause" if self._state.playback_state == PlaybackStateType.PLAYING else "play"
        shortcuts = Text()
        shortcuts.append("←", style=self._shortcut_style("prev"))
        shortcuts.append(" prev  ", style="dim")
        shortcuts.append("<space>", style=self._shortcut_style("space"))
        shortcuts.append(f" {space_label}  ", style="dim")
        shortcuts.append("→", style=self._shortcut_style("next"))
        shortcuts.append(" next  ", style="dim")
        shortcuts.append("g", style=self._shortcut_style("switch"))
        shortcuts.append(" change group", style="dim")
        content.add_row(shortcuts)

        return Panel(content, title="Now Playing", border_style="blue", expand=expand)

    def _build_progress_bar(self, *, expand: bool = False) -> Panel:
        """Build the progress bar panel."""
        progress_ms = self._state.track_progress_ms or 0
        duration_ms = self._state.track_duration_ms or 0

        # Interpolate progress if playing
        if (
            self._state.playback_state == PlaybackStateType.PLAYING
            and self._state.progress_updated_at > 0
            and duration_ms > 0
        ):
            elapsed_ms = (time.monotonic() - self._state.progress_updated_at) * 1000
            progress_ms = min(duration_ms, progress_ms + int(elapsed_ms))

        percentage = min(100, progress_ms / duration_ms * 100) if duration_ms > 0 else 0

        # Time text (fixed width)
        time_str = f"{self._format_time(progress_ms)} / {self._format_time(duration_ms)}"

        # Calculate bar width: terminal - panel borders (4) - time text - spacing
        bar_width = max(10, self._console.width - 4 - len(time_str) - 5)
        filled = int(bar_width * percentage / 100)
        empty = bar_width - filled

        bar = Text()
        bar.append("[", style="dim")
        bar.append("=" * filled, style="green bold")
        if filled < bar_width:
            bar.append(">", style="green bold")
            bar.append("-" * max(0, empty - 1), style="dim")
        bar.append("] ", style="dim")

        time_text_styled = Text()
        time_text_styled.append(self._format_time(progress_ms), style="cyan")
        time_text_styled.append(" / ", style="dim")
        time_text_styled.append(self._format_time(duration_ms), style="cyan")

        # Use grid to keep bar and time on same line
        content = Table.grid(expand=True, padding=0)
        content.add_column()
        content.add_column(justify="right", no_wrap=True)
        content.add_row(bar, time_text_styled)

        return Panel(content, title="Progress", border_style="green", expand=expand)

    def _build_volume_panel(self, *, expand: bool = False) -> Panel:
        """Build the volume panel."""
        # Info grid with label/value columns
        info = Table.grid(padding=(0, 2))
        info.add_column()
        info.add_column()

        # Group volume
        vol = self._state.volume if self._state.volume is not None else 0
        vol_style = "red" if self._state.muted else "cyan"
        vol_text = f"{vol}%" + (" [MUTED]" if self._state.muted else "")
        info.add_row("Group:", Text(vol_text, style=vol_style))

        # Player volume
        pvol = self._state.player_volume
        pvol_style = "red" if self._state.player_muted else "cyan"
        pvol_text = f"{pvol}%" + (" [MUTED]" if self._state.player_muted else "")
        info.add_row("Player:", Text(pvol_text, style=pvol_style))

        # Vertical container for info + shortcuts (5 lines total)
        content = Table.grid()
        content.add_column()
        content.add_row(info)
        content.add_row("")  # Line 3: spacing
        content.add_row("")  # Line 4: spacing

        # Line 5: volume shortcuts
        shortcuts = Text()
        shortcuts.append("↑", style=self._shortcut_style("up"))
        shortcuts.append(" up  ", style="dim")
        shortcuts.append("↓", style=self._shortcut_style("down"))
        shortcuts.append(" down  ", style="dim")
        shortcuts.append("m", style=self._shortcut_style("mute"))
        shortcuts.append(" mute", style="dim")
        content.add_row(shortcuts)

        return Panel(content, title="Volume", border_style="magenta", expand=expand)

    def _build_server_selector_panel(self) -> Panel:
        """Build the server selector panel."""
        content = Table.grid()
        content.add_column()

        if not self._state.available_servers:
            content.add_row("")
            content.add_row(Text("Searching for servers...", style="dim"))
            content.add_row("")
        else:
            for i, server in enumerate(self._state.available_servers):
                is_selected = i == self._state.selected_server_index
                is_current = server.url == self._state.server_url

                line = Text()
                if is_selected:
                    line.append(" > ", style="bold cyan")
                else:
                    line.append("   ")

                # Server name
                name_style = "bold white" if is_selected else "white"
                line.append(server.name, style=name_style)

                # Current server indicator
                if is_current:
                    line.append(" (current)", style="dim green")

                content.add_row(line)

                # Show URL below name
                url_line = Text()
                url_line.append("   ")
                url_style = "cyan" if is_selected else "dim"
                url_line.append(f"   {server.host}:{server.port}", style=url_style)
                content.add_row(url_line)

        content.add_row("")

        # Shortcuts
        shortcuts = Text()
        shortcuts.append("↑", style=self._shortcut_style("selector-up"))
        shortcuts.append("/", style="dim")
        shortcuts.append("↓", style=self._shortcut_style("selector-down"))
        shortcuts.append(" navigate  ", style="dim")
        shortcuts.append("<enter>", style=self._shortcut_style("selector-enter"))
        shortcuts.append(" connect", style="dim")
        content.add_row(shortcuts)

        return Panel(content, title="Select Server", border_style="cyan")

    def _build_layout(self) -> Table:
        """Build the complete UI layout."""
        # Get terminal width and leave 1 char margin to prevent wrapping
        width = self._console.width - 1

        # Main layout table
        layout = Table.grid(expand=False)
        layout.add_column(width=width)

        # Show server selector if active
        if self._state.show_server_selector:
            layout.add_row(self._build_server_selector_panel())
            return layout

        # Top row: Now Playing + Volume
        top_row = Table.grid(expand=True)
        top_row.add_column(ratio=2)
        top_row.add_column(ratio=1)
        top_row.add_row(
            self._build_now_playing_panel(expand=True),
            self._build_volume_panel(expand=True),
        )
        layout.add_row(top_row)

        # Progress bar
        layout.add_row(self._build_progress_bar(expand=True))

        # Status line at bottom
        layout.add_row(self._build_status_line())

        return layout

    def _build_status_line(self) -> Table:
        """Build the status line at the bottom."""
        # Left side: connection status + delay
        left = Text()
        left.append("  ")  # Align with panel content
        if self._state.connected and self._state.server_url:
            # Extract host from ws://host:port/path
            url = self._state.server_url
            host = url.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
            # Remove brackets from IPv6
            host = host.strip("[]")
            if self._state.group_name:
                left.append(f"Connected to {self._state.group_name} at {host}", style="dim")
            else:
                left.append(f"Connected to {host}", style="dim")
            # Add delay info
            delay = self._state.delay_ms
            if delay >= 0:
                left.append(f" · Delay: +{delay:.0f}ms", style="dim")
            else:
                left.append(f" · Delay: {delay:.0f}ms", style="dim")
        else:
            left.append(self._state.status_message, style="dim yellow")

        # Right side: delay shortcuts + server selector + quit shortcut
        right = Text()
        right.append("[", style=self._shortcut_style("delay-"))
        right.append("/", style="dim")
        right.append("]", style=self._shortcut_style("delay+"))
        right.append(" delay  ", style="dim")
        right.append("s", style=self._shortcut_style("server"))
        right.append(" server  ", style="dim")
        right.append("q", style=self._shortcut_style("quit"))
        right.append(" quit", style="dim")

        # Use grid for left/right alignment with padding column
        line = Table.grid(expand=True)
        line.add_column(ratio=1)
        line.add_column(justify="right")
        line.add_column(width=2)  # Right padding to align with panel interior
        line.add_row(left, right, "")
        return line

    def refresh(self) -> None:
        """Request a UI refresh."""
        if self._live is not None:
            self._live.refresh()

    def set_connected(self, url: str) -> None:
        """Update connection status to connected."""
        self._state.connected = True
        self._state.server_url = url
        self._state.status_message = f"Connected to {url}"
        self.refresh()

    def set_group_name(self, name: str | None) -> None:
        """Update the group name."""
        self._state.group_name = name
        self.refresh()

    def set_disconnected(self, message: str = "Disconnected") -> None:
        """Update connection status to disconnected."""
        self._state.connected = False
        self._state.status_message = message
        self.refresh()

    def set_playback_state(self, state: PlaybackStateType) -> None:
        """Update playback state."""
        # When leaving PLAYING, capture interpolated progress so display doesn't jump
        if (
            self._state.playback_state == PlaybackStateType.PLAYING
            and state != PlaybackStateType.PLAYING
            and self._state.progress_updated_at > 0
            and self._state.track_duration_ms
        ):
            elapsed_ms = (time.monotonic() - self._state.progress_updated_at) * 1000
            interpolated = (self._state.track_progress_ms or 0) + int(elapsed_ms)
            self._state.track_progress_ms = min(self._state.track_duration_ms, interpolated)
            # Reset timestamp so resume starts fresh from captured position
            self._state.progress_updated_at = time.monotonic()

        self._state.playback_state = state
        self.refresh()

    def set_metadata(
        self,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
    ) -> None:
        """Update track metadata."""
        self._state.title = title
        self._state.artist = artist
        self._state.album = album
        self.refresh()

    def set_progress(self, progress_ms: int | None, duration_ms: int | None) -> None:
        """Update track progress."""
        self._state.track_progress_ms = progress_ms
        self._state.track_duration_ms = duration_ms
        self._state.progress_updated_at = time.monotonic()
        self.refresh()

    def clear_progress(self) -> None:
        """Clear track progress completely, preventing any interpolation."""
        self._state.track_progress_ms = None
        self._state.track_duration_ms = None
        self._state.progress_updated_at = 0.0
        self.refresh()

    def set_volume(self, volume: int | None, *, muted: bool | None = None) -> None:
        """Update group volume."""
        if volume is not None:
            self._state.volume = volume
        if muted is not None:
            self._state.muted = muted
        self.refresh()

    def set_player_volume(self, volume: int, *, muted: bool) -> None:
        """Update player volume."""
        self._state.player_volume = volume
        self._state.player_muted = muted
        self.refresh()

    def set_delay(self, delay_ms: float) -> None:
        """Update the delay display."""
        self._state.delay_ms = delay_ms
        self.refresh()

    def show_server_selector(self, servers: list[DiscoveredServer]) -> None:
        """Show the server selector with available servers."""
        self._state.available_servers = servers
        self._state.selected_server_index = 0
        self._state.show_server_selector = True
        self.refresh()

    def hide_server_selector(self) -> None:
        """Hide the server selector."""
        self._state.show_server_selector = False
        self.refresh()

    def is_server_selector_visible(self) -> bool:
        """Check if the server selector is currently visible."""
        return self._state.show_server_selector

    def move_server_selection(self, delta: int) -> None:
        """Move the server selection by delta (-1 for up, +1 for down)."""
        if not self._state.available_servers:
            return
        new_index = self._state.selected_server_index + delta
        self._state.selected_server_index = max(
            0, min(len(self._state.available_servers) - 1, new_index)
        )
        self.refresh()

    def get_selected_server(self) -> DiscoveredServer | None:
        """Get the currently selected server."""
        if not self._state.available_servers:
            return None
        if 0 <= self._state.selected_server_index < len(self._state.available_servers):
            return self._state.available_servers[self._state.selected_server_index]
        return None

    def start(self) -> None:
        """Start the live display."""
        self._console.clear()
        self._live = Live(
            _RefreshableLayout(self),
            console=self._console,
            refresh_per_second=4,
            screen=True,
        )
        self._live.start()
        self._running = True

    def stop(self) -> None:
        """Stop the live display."""
        self._running = False
        if self._live is not None:
            self._live.stop()
            self._live = None

    def __enter__(self) -> SendspinTUI:
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        """Context manager exit."""
        self.stop()


class CommandHandler:
    """Handles keyboard commands."""

    def __init__(
        self,
        client: SendspinAudioClient,
        ui: SendspinTUI,
        discovery: ServiceDiscovery,
    ) -> None:
        """Initialize the command handler."""
        self._client = client
        self._ui = ui
        self._discovery = discovery

    async def send_media_command(self, command) -> None:
        """Send a media command with validation."""
        from aiosendspin.models.types import MediaCommand

        supported = self._client.get_supported_commands()
        if command not in supported:
            self._ui.state.status_message = f"Server does not support {command.value}"
            self._ui.refresh()
            return
        await self._client.send_media_command(command)

    async def toggle_play_pause(self) -> None:
        """Toggle between play and pause."""
        from aiosendspin.models.types import MediaCommand

        state = self._client.get_playback_state()
        if state == PlaybackStateType.PLAYING:
            await self.send_media_command(MediaCommand.PAUSE)
        else:
            await self.send_media_command(MediaCommand.PLAY)

    async def change_player_volume(self, delta: int) -> None:
        """Adjust player (local) volume by delta."""
        volume, muted = self._client.get_player_volume()
        target = max(0, min(100, volume + delta))
        self._client.set_volume(target, muted=muted)
        self._ui.set_player_volume(target, muted=muted)

    async def toggle_player_mute(self) -> None:
        """Toggle player (local) mute state."""
        volume, muted = self._client.get_player_volume()
        new_muted = not muted
        self._client.set_volume(volume, muted=new_muted)
        self._ui.set_player_volume(volume, muted=new_muted)

    async def adjust_delay(self, delta: float) -> None:
        """Adjust static delay by delta milliseconds."""
        # Note: delay adjustment requires reconnecting with new delay
        # For simplicity, we'll just update the UI display
        current_delay = self._ui.state.delay_ms
        new_delay = current_delay + delta
        self._ui.set_delay(new_delay)

    def open_server_selector(self) -> None:
        """Open the server selector panel."""
        servers = self._discovery.get_servers()
        self._ui.show_server_selector(servers)

    def close_server_selector(self) -> None:
        """Close the server selector panel."""
        self._ui.hide_server_selector()

    async def select_server(self) -> None:
        """Select the highlighted server and connect to it."""
        server = self._ui.get_selected_server()
        if server is not None and server.url != self._ui.state.server_url:
            self._ui.hide_server_selector()
            # Note: Reconnection would require recreating the client
            # For this example, we'll just update the UI
            self._ui.set_connected(server.url)
            self._ui.state.status_message = "Reconnect required - restart the application"
            self._ui.refresh()


async def keyboard_loop(
    client: SendspinAudioClient,
    ui: SendspinTUI,
    discovery: ServiceDiscovery,
) -> None:
    """Run the keyboard input loop."""
    from aiosendspin.models.types import MediaCommand

    handler = CommandHandler(client, ui, discovery)

    # Key dispatch table: key -> (highlight_name | None, async action)
    shortcuts: dict[str, tuple[str | None, Callable[[], asyncio.coroutine]]] = {
        # Letter keys
        " ": ("space", handler.toggle_play_pause),
        "m": ("mute", handler.toggle_player_mute),
        "g": ("switch", lambda: handler.send_media_command(MediaCommand.SWITCH)),
        # Delay adjustment
        "[": ("delay-", lambda: handler.adjust_delay(-10)),
        "]": ("delay+", lambda: handler.adjust_delay(10)),
        # Arrow keys
        readchar.key.LEFT: (
            "prev",
            lambda: handler.send_media_command(MediaCommand.PREVIOUS),
        ),
        readchar.key.RIGHT: (
            "next",
            lambda: handler.send_media_command(MediaCommand.NEXT),
        ),
        readchar.key.UP: ("up", lambda: handler.change_player_volume(5)),
        readchar.key.DOWN: ("down", lambda: handler.change_player_volume(-5)),
    }

    if not sys.stdin.isatty():
        logger.info("Running as daemon without interactive input")
        await asyncio.Event().wait()
        return

    # Interactive mode with single keypress input using readchar
    loop = asyncio.get_running_loop()

    while True:
        try:
            # Run blocking readkey in executor to not block the event loop
            key = await loop.run_in_executor(None, readchar.readkey)
        except (asyncio.CancelledError, KeyboardInterrupt):
            break

        # Handle Ctrl+C
        if key == "\x03":
            break

        # Handle server selector mode
        if ui.is_server_selector_visible():
            if key == readchar.key.UP:
                ui.highlight_shortcut("selector-up")
                ui.move_server_selection(-1)
                continue
            if key == readchar.key.DOWN:
                ui.highlight_shortcut("selector-down")
                ui.move_server_selection(1)
                continue
            if key in ("\r", "\n", readchar.key.ENTER):
                ui.highlight_shortcut("selector-enter")
                await handler.select_server()
                continue
            # Ignore other keys when selector is open
            continue

        # Handle quit
        if key in "q":
            ui.highlight_shortcut("quit")
            break

        # Handle 's' to open server selector
        if key in "sS":
            ui.highlight_shortcut("server")
            handler.open_server_selector()
            continue

        # Handle shortcuts via dispatch table (case-insensitive for letter keys)
        action = shortcuts.get(key) or shortcuts.get(key.lower())
        if action:
            highlight_name, action_handler = action
            if highlight_name:
                ui.highlight_shortcut(highlight_name)
            await action_handler()
            continue

        # Ignore unhandled escape sequences
        if key.startswith("\x1b"):
            continue


async def update_ui_from_client(client: SendspinAudioClient, ui: SendspinTUI) -> None:
    """Periodically update UI from client state."""
    while True:
        try:
            await asyncio.sleep(0.25)  # Update 4 times per second

            # Update metadata
            metadata = client.get_metadata()
            ui.set_metadata(
                title=metadata.get("title"),
                artist=metadata.get("artist"),
                album=metadata.get("album"),
            )

            # Update progress
            progress_ms, duration_ms = client.get_track_progress()
            if progress_ms is not None or duration_ms is not None:
                ui.set_progress(progress_ms, duration_ms)
            else:
                ui.clear_progress()

            # Update playback state
            playback_state = client.get_playback_state()
            if playback_state is not None:
                ui.set_playback_state(playback_state)

            # Update volume
            volume, muted = client.get_controller_volume()
            ui.set_volume(volume, muted=muted)

            # Update player volume
            player_volume, player_muted = client.get_player_volume()
            ui.set_player_volume(player_volume, muted=player_muted)

        except asyncio.CancelledError:
            break
        except Exception:
            # Ignore errors during update
            pass


async def main() -> None:
    """Main TUI application."""
    import argparse

    parser = argparse.ArgumentParser(description="Sendspin TUI Example")
    parser.add_argument(
        "--url",
        default=None,
        help="WebSocket URL of the Sendspin server. If omitted, discover via mDNS.",
    )
    parser.add_argument(
        "--audio-device",
        default=None,
        help="Audio device index or name prefix",
    )
    args = parser.parse_args()

    # Setup discovery
    discovery = ServiceDiscovery()
    await discovery.start()

    # Determine server URL
    url = args.url
    if url is None:
        print("Discovering servers...")
        try:
            url = await asyncio.wait_for(discovery.wait_for_first_server(), timeout=5.0)
        except asyncio.TimeoutError:
            servers = discovery.get_servers()
            if servers:
                url = servers[0].url
            else:
                print("No servers found. Exiting.")
                await discovery.stop()
                return

    # Resolve audio device
    audio_device = None
    if args.audio_device:
        devices = AudioDeviceManager.list_audio_devices()
        if args.audio_device.isnumeric():
            device_id = int(args.audio_device)
            audio_device = next((d for d in devices if d.index == device_id), None)
        else:
            audio_device = next(
                (d for d in devices if d.name.startswith(args.audio_device)), None
            )

    # Start UI first
    with SendspinTUI() as ui:
        # Create client
        config = SendspinAudioClientConfig(
            url=url,
            client_id="tui-client",
            client_name="TUI Example",
            audio_device=audio_device,
        )

        # Setup callbacks
        def on_metadata_update(metadata: dict) -> None:
            """Handle metadata updates."""
            pass  # Handled by update_ui_from_client

        def on_group_update(group_info: dict) -> None:
            """Handle group updates."""
            group_id = group_info.get("group_id")
            ui.set_group_name(group_id)

        def on_event(message: str) -> None:
            """Handle events."""
            ui.state.status_message = message
            ui.refresh()

        config.on_metadata_update = on_metadata_update
        config.on_group_update = on_group_update
        config.on_event = on_event

        client = SendspinAudioClient(config)
        ui.set_connected(url)

        try:
            # Connect client
            await client.connect()

            # Start UI update task
            update_task = asyncio.create_task(update_ui_from_client(client, ui))

            # Start keyboard loop
            keyboard_task = asyncio.create_task(keyboard_loop(client, ui, discovery))

            # Wait for keyboard loop to complete (user presses 'q')
            await keyboard_task

            # Cancel update task
            update_task.cancel()
            try:
                await update_task
            except asyncio.CancelledError:
                pass

        finally:
            await client.disconnect()
            await discovery.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

