"""Tests for building live-panel detail rows from allocations."""

from __future__ import annotations

from nd.nomad.models.allocation import AllocListStub, TaskState
from nd.ui.alloc_rows import alloc_children


def _task_state(state: str, *, failed: bool = False) -> TaskState:
    return TaskState(state=state, failed=failed, restarts=0)


def _alloc(
    name: str,
    group: str,
    node_id: str,
    status: str,
    task_states: dict[str, TaskState] | None = None,
) -> AllocListStub:
    return AllocListStub(
        id=name,
        name=name,
        node_id=node_id,
        job_id=group,
        task_group=group,
        client_status=status,
        desired_status="run",
        task_states_raw=task_states,
        create_index=1,
        modify_index=1,
    )


def test_alloc_children_builds_node_and_task_rows() -> None:
    """Verify an allocation renders a node row plus lifecycle-ordered task rows."""
    # Given one allocation on a named node with prestart, main, sidecar, and poststop tasks
    allocs = [
        _alloc(
            "cartlog.cartlog-group[0]",
            "cartlog-group",
            "node-aaaa",
            "pending",
            {
                "cartlog": _task_state("running"),
                "create_filesystem": _task_state("dead"),  # finished prestart task
                "cartlog_ezbak_sidecar": _task_state("pending"),
                "poststop-ezbak": _task_state("pending"),
            },
        )
    ]
    node_names = {"node-aaaa": "rpi2"}
    lifecycle = {
        "cartlog-group": {
            "create_filesystem": (0, "prestart"),
            "cartlog": (1000, "main"),
            "cartlog_ezbak_sidecar": (2000, "sidecar"),
        }
    }

    # When building the detail rows
    children = alloc_children(allocs, node_names, lifecycle)

    # Then the node row comes first at depth 1, labeled by the node name
    assert children[0].depth == 1
    assert "rpi2" in children[0].cells[0]
    # And the tasks follow at depth 2 in lifecycle order, poststop excluded
    task_rows = children[1:]
    assert all(c.depth == 2 for c in task_rows)
    assert [c.cells[0] for c in task_rows] == [
        "create_filesystem",
        "cartlog",
        "cartlog_ezbak_sidecar",
    ]
    roles = [c.cells[1] for c in task_rows]
    assert "prestart" in roles[0]
    assert "main" in roles[1]
    assert "sidecar" in roles[2]
    # And a finished prestart task reads as complete, not dead
    assert "complete" in task_rows[0].cells[2]
    assert "running" in task_rows[1].cells[2]


def test_alloc_children_shows_all_tasks_without_lifecycle() -> None:
    """Verify an empty lifecycle map shows every task by name, including post-stop ones."""
    # Given an allocation draining, with a stopped main task and a running cleanup task
    allocs = [
        _alloc(
            "web.web[0]",
            "web",
            "n1",
            "running",
            {"web": _task_state("dead"), "cleanup": _task_state("running")},
        )
    ]

    # When building rows with no lifecycle metadata (e.g. during a stop)
    children = alloc_children(allocs, {"n1": "rpi2"}, {})

    # Then every task is shown, sorted by name, with no role label
    task_rows = [c for c in children if c.depth == 2]
    assert [c.cells[0] for c in task_rows] == ["cleanup", "web"]
    assert all(c.cells[1] == "" for c in task_rows)
    assert "running" in task_rows[0].cells[2]
    assert "complete" in task_rows[1].cells[2]  # a cleanly stopped task reads complete


def test_alloc_children_stopping_colors_and_relabels() -> None:
    """Verify stopping mode reads terminal rows as green "stopped" and others yellow."""
    # Given an allocation still draining: node running, one task stopped, one still alive
    allocs = [
        _alloc(
            "web.web[0]",
            "web",
            "n1",
            "running",
            {"web": _task_state("dead"), "cleanup": _task_state("running")},
        )
    ]

    # When building rows in stopping mode
    children = alloc_children(allocs, {"n1": "rpi2"}, {}, stopping=True)

    # Then the still-running node row reads yellow (we are waiting on it)
    node_row = next(c for c in children if c.depth == 1)
    assert node_row.cells[2] == "[yellow]• running[/]"
    # And the cleanly stopped task reads green "stopped", not "complete"
    task_rows = {c.cells[0]: c for c in children if c.depth == 2}
    assert task_rows["web"].cells[2] == "[green]✓ stopped[/]"
    # And the still-alive cleanup task reads yellow
    assert task_rows["cleanup"].cells[2] == "[yellow]• running[/]"


def test_alloc_children_disambiguates_duplicate_nodes() -> None:
    """Verify two allocations on the same node get a #index suffix."""
    # Given two allocations placed on the same node
    allocs = [
        _alloc("web.web[0]", "web", "n1", "running"),
        _alloc("web.web[1]", "web", "n1", "running"),
    ]

    # When building the detail rows
    children = alloc_children(allocs, {"n1": "rpi2"}, {})

    # Then each node row is suffixed with the allocation index to stay distinct
    node_labels = [c.cells[0] for c in children if c.depth == 1]
    assert "rpi2 #0" in node_labels[0]
    assert "rpi2 #1" in node_labels[1]
