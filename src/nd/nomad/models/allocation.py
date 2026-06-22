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
    create_index: int
    modify_index: int


class Allocation(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """An allocation as returned by ``GET /v1/allocation/:id``."""

    id: str = msgspec.field(name="ID")
    name: str
    namespace: str = "default"
    node_id: str = msgspec.field(name="NodeID")
    job_id: str = msgspec.field(name="JobID")
    task_group: str
    client_status: str
    desired_status: str
    task_states: dict[str, TaskState] = msgspec.field(name="TaskStates", default_factory=dict)
    create_index: int
    modify_index: int
