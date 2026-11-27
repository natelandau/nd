"""Shared status styling: a single source of truth for colors and glyphs."""

from __future__ import annotations

from typing import Literal

from rich.theme import Theme

from nd.constants import FAILED_ALLOC_STATUSES

# Maps a Nomad status string to the Rich color used for its cell.
STATUS_STYLE: dict[str, str] = {
    "ready": "green",
    "running": "green",
    "complete": "green",
    "alive": "green",
    "successful": "green",
    "pending": "yellow",
    "degraded": "yellow",
    "initializing": "yellow",
    "draining": "yellow",
    "leaving": "yellow",
    "paused": "yellow",
    "blocked": "yellow",
    "down": "red",
    "dead": "red",
    "failed": "red",
    "lost": "red",
    "disconnected": "red",
    "cancelled": "red",
}

# Outcome glyphs for terminal command results, keyed by a stable severity name.
OUTCOME_GLYPH: dict[str, str] = {
    "ok": "[green]✓[/]",
    "warn": "[yellow]⚠[/]",
    "fail": "[red]✗[/]",
}


# Statuses that mean a workload has finished stopping cleanly, rendered as green
# "stopped" during a drain.
_STOPPED_STATUSES = frozenset({"complete", "stopped"})


def status_style(status: str) -> str:
    """Return the Rich color registered for a status, or "default" when unknown.

    Lets a caller tint other cells (e.g. a degraded job's name) with the exact color
    ``status_cell`` uses for the same status, so they stay in sync from one source.
    """
    return STATUS_STYLE.get(status, "default")


def status_cell(status: str, *, stopping: bool = False) -> str:
    """Render a status string as a colored glyph plus label for a table cell.

    Centralizes status coloring so every command shows the same color for the
    same Nomad state. With ``stopping`` set (during a stop/drain) the meaning of a
    state inverts: the goal is a stopped workload, so a cleanly terminal allocation
    reads green as "stopped" while every transitional state we are still waiting on
    (running, pending, ...) reads yellow; a genuine failure stays red.
    """
    if stopping:
        if status in _STOPPED_STATUSES:
            return "[green]✓ stopped[/]"
        # A genuine failure mid-stop stays red rather than yellow so a crash on shutdown or a
        # lost node does not blend in with the rows still draining.
        if status in FAILED_ALLOC_STATUSES:
            return f"[red]✗ {status}[/]"
        return f"[yellow]• {status}[/]"
    style = status_style(status)
    glyph = {"green": "✓", "red": "✗"}.get(style, "•")
    return f"[{style}]{glyph} {status}[/]"


def accent(text: str) -> str:
    """Style text as a key identifier (e.g. a node name) so it stands out."""
    return f"[cyan]{text}[/]"


def muted(text: str) -> str:
    """Style text as secondary metadata so it recedes from the primary content."""
    return f"[dim]{text}[/]"


# Log view: colors repeat once a palette runs out. Red is left out because it marks errors.
LOG_TASK_PALETTE: tuple[str, ...] = (
    "cyan",
    "magenta",
    "green",
    "yellow",
    "bright_blue",
    "bright_magenta",
    "bright_green",
    "bright_cyan",
)
LOG_ALLOC_PALETTE: tuple[str, ...] = (
    "bright_yellow",
    "bright_cyan",
    "bright_magenta",
    "bright_green",
    "bright_blue",
    "orange3",
    "turquoise2",
    "medium_purple",
)
LOG_STDERR_GLYPH = "!"
LOG_STDERR_STYLE = "yellow"
LOG_MATCH_STYLE = "reverse bold"
LOG_LIFECYCLE_STYLE = "dim"
# What a dim lifecycle line of the log views reports
type LifecycleEvent = Literal[
    "started", "stopped", "failed", "lost-stream", "reconnected", "waiting"
]
# Leading glyph of each lifecycle line, keyed by event.
LOG_LIFECYCLE_GLYPH: dict[LifecycleEvent, str] = {
    "started": "+",
    "stopped": "-",
    "failed": "x",
    "lost-stream": "x",
    "reconnected": "+",
    "waiting": ".",
}

# Styles `LogHighlighter` applies; its `log.` base style plus a pattern group name selects one.
LOG_THEME = Theme(
    {
        "log.level_error": "bold red",
        "log.level_warn": "bold yellow",
        "log.level_info": "green",
        "log.level_debug": "dim",
        "log.timestamp": "dim cyan",
        "log.ip": "magenta",
        "log.uuid": "magenta",
        "log.url": "underline blue",
        "log.number": "cyan",
        "log.key": "bright_blue",
        "log.string": "green",
    }
)
