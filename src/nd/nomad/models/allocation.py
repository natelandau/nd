"""Models for the Nomad allocations endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import msgspec

from nd.constants import TERMINAL_ALLOC_STATUSES
from nd.nomad.models import NomadModel

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# Desired statuses Nomad assigns to allocations it has retired (rescheduled, drained,
# superseded). Their client_status is historical, not a reflection of current health.
_RETIRED_DESIRED_STATUSES = frozenset({"stop", "evict"})


class TaskState(NomadModel, frozen=True, kw_only=True):
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

    @property
    def started_at_ns(self) -> int:
        """The task's start time in unix nanoseconds, or 0 when it is unusable.

        Use this to anchor a task's run time. Nomad emits a zero sentinel
        ("0001-01-01T00:00:00Z") before a task starts and 9 fractional digits once it
        has. Blanks, unparsable input, the sentinel, and a timestamp carrying no UTC
        offset (whose true instant is unknowable) all read as 0 so the caller can fall
        back to another anchor. Integer date math keeps the result exact.
        """
        if not self.started_at:
            return 0
        try:
            parsed = datetime.fromisoformat(self.started_at)
        except ValueError:
            return 0
        if parsed.tzinfo is None:
            return 0
        delta = parsed - _EPOCH
        ns = (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000
        return max(0, ns)


class AllocListStub(NomadModel, frozen=True, kw_only=True):
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
    next_allocation: str = ""
    # Nomad sends TaskStates: null (not an empty object) for a freshly-placed
    # allocation whose tasks have not started yet, so this must tolerate null.
    task_states_raw: dict[str, TaskState] | None = msgspec.field(name="TaskStates", default=None)
    # Unix-nanosecond timestamp of when Nomad created (placed) this allocation; used as
    # the run-time anchor when a task's StartedAt is unavailable.
    create_time: int = 0
    create_index: int
    modify_index: int

    @property
    def task_states(self) -> dict[str, TaskState]:
        """Per-task run state, with Nomad's null (tasks not yet started) read as empty."""
        return self.task_states_raw or {}

    @property
    def is_terminal(self) -> bool:
        """Whether the allocation has fully stopped, poststop lifecycle tasks included.

        Use this to tell when a stopped job has finished draining.
        """
        return self.client_status in TERMINAL_ALLOC_STATUSES

    @property
    def is_retired(self) -> bool:
        """Whether Nomad has intentionally retired this allocation (desired stop or evict).

        A retired allocation's client status is historical, so it must not count toward
        current cluster health.
        """
        return self.desired_status in _RETIRED_DESIRED_STATUSES

    @property
    def is_replaced(self) -> bool:
        """Whether Nomad has superseded this allocation with a newer one in a reschedule chain.

        A failed or lost allocation keeps desired status "run" while it lingers in
        history, so a set ``next_allocation`` (not the desired status) is what tells a
        corpse whose replacement is already running apart from the head of the chain.
        A replaced corpse is not a live problem.
        """
        return bool(self.next_allocation)
