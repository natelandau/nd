"""Build live-panel detail rows from Nomad allocations.

Turns a job's allocations into the indented ``LiveChild`` rows shown under a
``LiveRow``: one node row per allocation, then a row per task. Shared by the
commands that watch a job change state (``nd run`` deploy, ``nd stop`` drain).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from nd.ui.live_panel import LiveChild
from nd.ui.styles import accent, muted, status_cell

if TYPE_CHECKING:
    from nd.nomad.models.allocation import AllocListStub

# Per group, a map of task name to its (sort order, lifecycle label).
type TaskLifecycle = dict[str, dict[str, tuple[int, str]]]


def alloc_children(
    allocs: list[AllocListStub], node_names: dict[str, str], lifecycle: TaskLifecycle
) -> list[LiveChild]:
    """Build the detail rows for a job: one node row per allocation, then its tasks.

    Each allocation contributes a depth-1 row labeled by the node it landed on
    (with a ``#index`` suffix when two allocations share a node), followed by a
    depth-2 row per task showing the task's lifecycle role and translated state.
    Allocations are sorted by name so the rows stay stable across polls.

    Args:
        allocs: The job's current allocations.
        node_names: Map of node ID to node name for placement display.
        lifecycle: Task ordering and labels from a compiled job spec, or an empty
            map to show every task by name (used when no spec is on hand).

    Returns:
        The ordered detail rows: node rows at depth 1, task rows at depth 2.
    """
    node_counts = Counter(alloc.node_id for alloc in allocs)
    children: list[LiveChild] = []
    for alloc in sorted(allocs, key=lambda a: a.name):
        node = _alloc_node_label(alloc, node_names, ambiguous=node_counts[alloc.node_id] > 1)
        children.append(
            LiveChild(cells=[accent(node), "", status_cell(alloc.client_status)], depth=1)
        )
        children.extend(_task_rows(alloc, lifecycle.get(alloc.task_group, {})))
    return children


def _alloc_node_label(alloc: AllocListStub, node_names: dict[str, str], *, ambiguous: bool) -> str:
    """Label an allocation by its node, appending the alloc index when a node repeats."""
    node = node_names.get(alloc.node_id, alloc.node_id[:8])
    if not ambiguous:
        return node
    bracket = alloc.name.rfind("[")
    index = alloc.name[bracket + 1 : -1] if bracket != -1 and alloc.name.endswith("]") else "?"
    return f"{node} #{index}"


def _task_rows(alloc: AllocListStub, roles: dict[str, tuple[int, str]]) -> list[LiveChild]:
    """Build the depth-2 task rows for one allocation, ordered by lifecycle.

    With lifecycle metadata, only its tasks are shown (poststop already excluded),
    ordered prestart, main, then sidecar. Without it, every task is shown by name as
    a fallback so a missing spec never hides the tasks.
    """
    if roles:
        names = sorted((n for n in alloc.task_states if n in roles), key=lambda n: roles[n][0])
        labeled = [(n, roles[n][1]) for n in names]
    else:
        labeled = [(n, "") for n in sorted(alloc.task_states)]
    rows: list[LiveChild] = []
    for name, role in labeled:
        ts = alloc.task_states[name]
        role_cell = muted(role) if role else ""
        status = status_cell(_task_status(ts.state, failed=ts.failed))
        rows.append(LiveChild(cells=[name, role_cell, status], depth=2))
    return rows


def _task_status(state: str, *, failed: bool) -> str:
    """Translate a raw task state into a status word the styling layer colors well.

    A finished task reports the raw state ``dead``; render it as ``complete`` or
    ``failed`` so it reads as success or failure rather than an error.
    """
    if state == "dead":
        return "failed" if failed else "complete"
    return state
