"""Tests for building live-panel detail rows from allocations."""

from __future__ import annotations

from nd.ui.alloc_rows import alloc_children


class _TS:
    def __init__(self, state: str, *, failed: bool = False) -> None:
        self.state = state
        self.failed = failed


class _Alloc:
    def __init__(
        self, name: str, group: str, node_id: str, status: str, task_states: dict | None = None
    ) -> None:
        self.name = name
        self.task_group = group
        self.node_id = node_id
        self.client_status = status
        self.task_states = task_states or {}


def test_alloc_children_builds_node_and_task_rows() -> None:
    """Verify an allocation renders a node row plus lifecycle-ordered task rows."""
    # Given one allocation on a named node with prestart, main, sidecar, and poststop tasks
    allocs = [
        _Alloc(
            "cartlog.cartlog-group[0]",
            "cartlog-group",
            "node-aaaa",
            "pending",
            {
                "cartlog": _TS("running"),
                "create_filesystem": _TS("dead"),  # finished prestart task
                "cartlog_ezbak_sidecar": _TS("pending"),
                "poststop-ezbak": _TS("pending"),
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
    children = alloc_children(allocs, node_names, lifecycle)  # type: ignore[arg-type]

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
        _Alloc(
            "web.web[0]",
            "web",
            "n1",
            "running",
            {"web": _TS("dead"), "cleanup": _TS("running")},
        )
    ]

    # When building rows with no lifecycle metadata (e.g. during a stop)
    children = alloc_children(allocs, {"n1": "rpi2"}, {})  # type: ignore[arg-type]

    # Then every task is shown, sorted by name, with no role label
    task_rows = [c for c in children if c.depth == 2]
    assert [c.cells[0] for c in task_rows] == ["cleanup", "web"]
    assert all(c.cells[1] == "" for c in task_rows)
    assert "running" in task_rows[0].cells[2]
    assert "complete" in task_rows[1].cells[2]  # a cleanly stopped task reads complete


def test_alloc_children_disambiguates_duplicate_nodes() -> None:
    """Verify two allocations on the same node get a #index suffix."""
    # Given two allocations placed on the same node
    allocs = [
        _Alloc("web.web[0]", "web", "n1", "running"),
        _Alloc("web.web[1]", "web", "n1", "running"),
    ]

    # When building the detail rows
    children = alloc_children(allocs, {"n1": "rpi2"}, {})  # type: ignore[arg-type]

    # Then each node row is suffixed with the allocation index to stay distinct
    node_labels = [c.cells[0] for c in children if c.depth == 1]
    assert "rpi2 #0" in node_labels[0]
    assert "rpi2 #1" in node_labels[1]
