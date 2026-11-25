"""Tests for building live-panel detail rows from allocations."""

from __future__ import annotations

from nd.ui.alloc_rows import alloc_children
from nd.ui.styles import status_cell
from tests.builders import alloc_stub, task_state


def test_alloc_children_builds_node_and_task_rows() -> None:
    """Verify an allocation renders a node row plus lifecycle-ordered task rows."""
    # Given one allocation on a named node with prestart, main, sidecar, and poststop tasks
    allocs = [
        alloc_stub(
            job_id="cartlog",
            task_group="cartlog-group",
            node_id="node-aaaa",
            client_status="pending",
            task_states={
                "cartlog": task_state("running"),
                "create_filesystem": task_state("dead"),  # finished prestart task
                "cartlog_ezbak_sidecar": task_state("pending"),
                "poststop-ezbak": task_state("pending"),
            },
        )
    ]
    lifecycle = {
        "cartlog-group": {
            "create_filesystem": (0, "prestart"),
            "cartlog": (1000, "main"),
            "cartlog_ezbak_sidecar": (2000, "sidecar"),
        }
    }

    # When building the detail rows
    children = alloc_children(allocs=allocs, node_names={"node-aaaa": "rpi2"}, lifecycle=lifecycle)

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
    allocs = [alloc_stub(task_states={"web": task_state("dead"), "cleanup": task_state("running")})]

    # When building rows with no lifecycle metadata (e.g. during a stop)
    children = alloc_children(allocs=allocs, node_names={"n1": "rpi2"}, lifecycle={})

    # Then every task is shown, sorted by name, with no role label
    task_rows = [c for c in children if c.depth == 2]
    assert [c.cells[0] for c in task_rows] == ["cleanup", "web"]
    assert all(c.cells[1] == "" for c in task_rows)
    assert "running" in task_rows[0].cells[2]
    assert "complete" in task_rows[1].cells[2]  # a cleanly stopped task reads complete


def test_alloc_children_stopping_reads_rows_as_stopping() -> None:
    """Verify stopping mode renders every node and task status as it reads during a stop."""
    # Given an allocation still draining: node running, one task stopped, one still alive
    allocs = [alloc_stub(task_states={"web": task_state("dead"), "cleanup": task_state("running")})]

    # When building rows in stopping mode
    children = alloc_children(allocs=allocs, node_names={"n1": "rpi2"}, lifecycle={}, stopping=True)

    # Then the still-running node row reads as waited on
    node_row = next(c for c in children if c.depth == 1)
    assert node_row.cells[2] == status_cell("running", stopping=True)
    # And the cleanly stopped task reads "stopped", not "complete"
    task_rows = {c.cells[0]: c for c in children if c.depth == 2}
    assert task_rows["web"].cells[2] == status_cell("complete", stopping=True)
    # And the still-alive cleanup task reads as waited on
    assert task_rows["cleanup"].cells[2] == status_cell("running", stopping=True)


def test_alloc_children_disambiguates_duplicate_nodes() -> None:
    """Verify two allocations on the same node get a #index suffix."""
    # Given two allocations placed on the same node
    allocs = [
        alloc_stub("a0", name="web.web[0]"),
        alloc_stub("a1", name="web.web[1]"),
    ]

    # When building the detail rows
    children = alloc_children(allocs=allocs, node_names={"n1": "rpi2"}, lifecycle={})

    # Then each node row is suffixed with the allocation index to stay distinct
    node_labels = [c.cells[0] for c in children if c.depth == 1]
    assert "rpi2 #0" in node_labels[0]
    assert "rpi2 #1" in node_labels[1]
