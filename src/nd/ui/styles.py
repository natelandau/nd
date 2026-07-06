"""Shared status styling: a single source of truth for colors and glyphs."""

from __future__ import annotations

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
