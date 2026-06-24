"""Tests for the generic live progress panel."""

from __future__ import annotations

import asyncio

from rich.console import Console

from nd.ui.live_panel import (
    LiveChild,
    LiveRow,
    _build_panel,
    _last_siblings,
    finish_row,
    run_live_panel,
)
from nd.ui.styles import OUTCOME_GLYPH


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


def test_last_siblings_marks_branch_ends() -> None:
    """Verify only the final sibling at each depth is flagged, across nested branches."""
    # Given two node branches, the first with two tasks and the second with one
    children = [
        LiveChild(cells=["node1"], depth=1),
        LiveChild(cells=["task1"], depth=2),
        LiveChild(cells=["task2"], depth=2),
        LiveChild(cells=["node2"], depth=1),
        LiveChild(cells=["task3"], depth=2),
    ]

    # When computing which rows close their branch
    # Then a row is last only when no later row shares its depth before the branch closes
    assert _last_siblings(children) == [False, False, True, True, True]


def test_build_panel_uses_branch_connectors() -> None:
    """Verify mid-branch children use ├ and only the final sibling uses └."""
    # Given a node with two tasks beneath it
    row = LiveRow(
        label="seer",
        phase="running",
        started_at=0.0,
        children=[
            LiveChild(cells=["rpi2", "", "running"], depth=1),
            LiveChild(cells=["create_filesystem", "prestart", "complete"], depth=2),
            LiveChild(cells=["seer", "main", "running"], depth=2),
        ],
    )
    console = Console(record=True, force_terminal=False, width=80)

    # When rendering the panel
    console.print(_build_panel([row], title="Deploying 1 job", now=1.0))
    lines = console.export_text().splitlines()

    # Then the only node closes its branch, the non-final task continues, the final closes
    assert "└" in next(line for line in lines if "rpi2" in line)
    assert "├" in next(line for line in lines if "create_filesystem" in line)
    assert "└" in next(line for line in lines if "main" in line)


def test_build_panel_separates_groups_with_a_rule() -> None:
    """Verify a horizontal rule divides adjacent job groups but never leads the first."""
    # Given two parent rows
    rows = [
        LiveRow(label="ladder", phase="deployed", started_at=0.0),
        LiveRow(label="seer", phase="deployed", started_at=0.0),
    ]
    console = Console(record=True, force_terminal=False, width=60)

    # When rendering the panel
    console.print(_build_panel(rows, title="Deployed 2 jobs", now=1.0))
    lines = console.export_text().splitlines()

    # Then a run of box-drawing dashes appears between the two groups
    rule_lines = [
        i for i, line in enumerate(lines) if "────" in line and "╭" not in line and "╰" not in line
    ]
    ladder_line = next(i for i, line in enumerate(lines) if "ladder" in line)
    seer_line = next(i for i, line in enumerate(lines) if "seer" in line)
    assert any(ladder_line < i < seer_line for i in rule_lines)


def test_build_panel_dims_children_after_healthy_finish() -> None:
    """Verify a healthy-finished parent's detail rows dim while an in-flight one's stay bright."""
    # Given one finished-healthy parent and one still-running parent, each with a child
    child = LiveChild(cells=["worker", "main", "running"], depth=1)
    finished = LiveRow(
        label="seer",
        phase="deployed",
        started_at=0.0,
        glyph=OUTCOME_GLYPH["ok"],
        ended_at=5.0,
        children=[child],
    )
    running = LiveRow(label="sonarr", phase="deploying", started_at=0.0, children=[child])

    def child_line(row: LiveRow) -> str:
        console = Console(record=True, force_terminal=True, width=60)
        console.print(_build_panel([row], title="t", now=9.0))
        return next(
            line for line in console.export_text(styles=True).splitlines() if "running" in line
        )

    # When rendering each parent's child row with styling
    # Then the finished parent's child status is dim-wrapped and the in-flight one's is not
    assert "\x1b[2mrunning" in child_line(finished)
    assert "\x1b[2mrunning" not in child_line(running)
