"""Models for the Nomad allocations endpoints."""

from __future__ import annotations

import msgspec


class TaskState(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """Run state of a single task within an allocation."""

    state: str
    failed: bool
    restarts: int
    # RFC3339 timestamp of when the task last started running. Nomad sends an explicit
    # null (not an absent key) before the task has started, which a plain str default
    # would not tolerate, so coerce it via the `started_at` property below.
    started_at_raw: str | None = msgspec.field(name="StartedAt", default=None)

    @property
    def started_at(self) -> str:
        """The task's start time, with Nomad's null (task not yet started) read as empty."""
        return self.started_at_raw or ""


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
    # Set to the id of the alloc that superseded this one in a reschedule chain; empty
    # when this is the head (latest) attempt. Distinguishes a failed corpse that recovered
    # (a replacement is running) from one Nomad has not been able to replace.
    next_allocation: str = msgspec.field(name="NextAllocation", default="")
    # Nomad sends TaskStates: null (not an empty object) for a freshly-placed
    # allocation whose tasks have not started yet, so this must tolerate null.
    task_states_raw: dict[str, TaskState] | None = msgspec.field(name="TaskStates", default=None)
    # Unix-nanosecond timestamp of when Nomad created (placed) this allocation; used as
    # the run-time anchor when a task's StartedAt is unavailable.
    create_time: int = msgspec.field(name="CreateTime", default=0)
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
