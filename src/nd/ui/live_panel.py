"""A reusable concurrent live progress panel.

Runs N async workers at once and renders a single Rich ``Live`` panel: a spinner
for in-flight rows, an outcome glyph for finished ones, with per-row phase text
and elapsed time. Used by ``nd stop`` (drain) and ``nd run`` (deploy).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from nclutils import pp
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table

from nd.ui.duration import fmt_elapsed
from nd.ui.panels import titled_panel

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from rich.console import Console
    from rich.panel import Panel


@dataclass(frozen=True)
class LiveChild:
    """One indented detail row beneath a ``LiveRow``, as plain display cells.

    ``depth`` sets the indent level (1 is directly under the parent row), so a
    caller can render a small tree of detail rows.
    """

    cells: list[str]
    depth: int = 1


@dataclass
class LiveRow:
    """Mutable per-worker state backing one row of a live panel."""

    label: str
    phase: str
    started_at: float
    glyph: str | None = None
    ended_at: float | None = None
    children: list[LiveChild] = field(default_factory=list)


class PanelUpdate(Protocol):
    """Callback a worker uses to refresh its row's phase text and child rows."""

    def __call__(self, phase: str, children: Sequence[LiveChild] = ()) -> None:
        """Set the row's phase text and detail rows, then re-render the panel."""
        ...


def finish_row(
    row: LiveRow, glyph: str, phase: str, *, clock: Callable[[], float] = time.monotonic
) -> None:
    """Record a row's terminal glyph, phase label, and end time."""
    row.glyph = glyph
    row.phase = phase
    row.ended_at = clock()


def _build_panel(rows: list[LiveRow], *, title: str, now: float) -> Panel:
    """Render the panel: a spinner for in-flight rows, a glyph for finished ones.

    Parent rows are bold and carry the spinner/glyph; child rows nest under them
    with a tree marker indented inside the label column so the text follows the
    tree rather than staying flush left.
    """
    table = Table.grid(padding=(0, 2))
    table.add_column()  # spinner / glyph (parent rows only)
    # no_wrap keeps the tree marker attached to its label on a narrow terminal
    # (the label truncates with an ellipsis instead of splitting across lines).
    table.add_column(no_wrap=True)  # label, tree-indented for children
    table.add_column()  # phase / role
    table.add_column(justify="right")  # elapsed / status
    for row in rows:
        glyph = Spinner("dots") if row.glyph is None else row.glyph
        ended = row.ended_at if row.ended_at is not None else now
        table.add_row(
            glyph, f"[bold]{row.label}[/]", row.phase, fmt_elapsed(ended - row.started_at)
        )
        for child in row.children:
            cells = [*child.cells[:3], "", "", ""][:3]  # pad/truncate to the 3 detail columns
            label = f"[dim]{'  ' * child.depth}└[/] {cells[0]}"
            table.add_row("", label, cells[1], cells[2])
    return titled_panel(table, title)


async def run_live_panel(
    rows: list[LiveRow],
    worker: Callable[[LiveRow, PanelUpdate], Awaitable[None]],
    *,
    running_title: str,
    final_title: Callable[[float], str],
    console: Console | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Run ``worker`` for every row concurrently under one live panel.

    Each worker receives its row and an ``update(phase, children=())`` callback
    that refreshes the row's phase text and optional indented detail rows, then
    re-renders the panel. Workers set their own terminal glyph via ``finish_row``.
    When all workers finish the title swaps to ``final_title(elapsed_seconds)``.

    Args:
        rows: Per-worker state rows; one per concurrent unit of work.
        worker: Async callable receiving ``(row, update)``; responsible for
            calling ``finish_row`` before returning.
        running_title: Panel title shown while work is in progress.
        final_title: Callable that receives elapsed seconds and returns the
            title shown after all workers complete.
        console: Rich console to render into. Defaults to ``pp.console()``.
        clock: Monotonic clock callable used for elapsed-time accounting.
            Injectable so tests avoid real wall-clock calls.
    """
    console = console or pp.console()
    start = clock()

    def panel(title: str) -> Panel:
        return _build_panel(rows, title=title, now=clock())

    with Live(panel(running_title), console=console, refresh_per_second=12) as live:

        async def run_one(row: LiveRow) -> None:
            def update(phase: str, children: Sequence[LiveChild] = ()) -> None:
                row.phase = phase
                row.children = list(children)
                live.update(panel(running_title))

            await worker(row, update)
            live.update(panel(running_title))

        await asyncio.gather(*(run_one(row) for row in rows))
        live.update(panel(final_title(clock() - start)))
