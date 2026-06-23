"""Tests for the generic live progress panel."""

from __future__ import annotations

import asyncio

from rich.console import Console

from nd.ui.live_panel import LiveChild, LiveRow, _build_panel, finish_row, run_live_panel


def test_run_live_panel_runs_all_workers() -> None:
    """Verify every row's worker runs and its terminal glyph is recorded."""
    # Given two rows and a fake monotonic clock
    ticks = iter(range(1000))
    clock = lambda: float(next(ticks))  # noqa: E731
    rows = [LiveRow(label=f"job{i}", phase="starting", started_at=0.0) for i in range(2)]

    async def worker(row: LiveRow, set_phase) -> None:
        set_phase("working")
        finish_row(row, "[green]✓[/]", "done", clock=clock)

    # When
    asyncio.run(
        run_live_panel(
            rows,
            worker,
            running_title="Running 2 jobs",
            final_title=lambda secs: f"Done in {int(secs)}s",
            console=Console(record=True, force_terminal=False),
            clock=clock,
        )
    )
    # Then
    assert all(row.glyph == "[green]✓[/]" for row in rows)
    assert all(row.phase == "done" for row in rows)
    assert all(row.ended_at is not None for row in rows)


def test_build_panel_renders_nested_child_rows() -> None:
    """Verify children render as indented detail rows, deeper for higher depth."""
    # Given a parent row with a depth-1 node row and a deeper depth-2 task row
    row = LiveRow(
        label="ladder",
        phase="running: 1/1 healthy",
        started_at=0.0,
        children=[
            LiveChild(cells=["rpi2", "", "running"], depth=1),
            LiveChild(cells=["create_filesystem", "prestart", "complete"], depth=2),
        ],
    )
    console = Console(record=True, force_terminal=False, width=80)

    # When rendering the panel
    console.print(_build_panel([row], title="Deploying 1 job", now=1.0))
    text = console.export_text()

    # Then the parent, the node row, and the deeper task row all appear
    assert "ladder" in text
    assert "rpi2" in text
    assert "create_filesystem" in text
    assert "prestart" in text
    # And the depth-2 task row is indented further than the depth-1 node row
    node_indent = next(line.index("└") for line in text.splitlines() if "rpi2" in line)
    task_indent = next(line.index("└") for line in text.splitlines() if "create_filesystem" in line)
    assert task_indent > node_indent
