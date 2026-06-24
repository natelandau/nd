"""Models for the Nomad allocations endpoints."""

from __future__ import annotations

import msgspec


class TaskState(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """Run state of a single task within an allocation."""

    state: str
    failed: bool
    restarts: int


class AllocListStub(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """An allocation as returned by ``GET /v1/allocations``."""

    id: str = msgspec.field(name="ID")
    name: str
    namespace: str = "default"
    node_id: str = msgspec.field(name="NodeID")
    job_id: str = msgspec.field(name="JobID")
    task_group: str
    client_status: str
    desired_status: str
    # Nomad sends TaskStates: null (not an empty object) for a freshly-placed
    # allocation whose tasks have not started yet, so this must tolerate null.
    task_states_raw: dict[str, TaskState] | None = msgspec.field(name="TaskStates", default=None)
    create_index: int
    modify_index: int

    @property
    def task_states(self) -> dict[str, TaskState]:
        """Per-task run state, with Nomad's null (tasks not yet started) read as empty."""
        return self.task_states_raw or {}


class Allocation(AllocListStub, frozen=True, kw_only=True):
    """An allocation as returned by ``GET /v1/allocation/:id``.

    The single-allocation endpoint returns the same shape as the list endpoint, so
    this carries the list stub's fields unchanged under a name that documents intent.
    """
