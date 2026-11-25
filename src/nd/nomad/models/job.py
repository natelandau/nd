"""Models for the Nomad jobs endpoints."""

from __future__ import annotations

import msgspec

from nd.nomad.models import NomadModel


class JobListStub(NomadModel, frozen=True, kw_only=True):
    """A job as returned by ``GET /v1/jobs``."""

    id: str = msgspec.field(name="ID")
    name: str
    type: str
    status: str
    priority: int
    namespace: str = "default"
    submit_time: int = 0
    create_index: int
    modify_index: int

    @property
    def is_running(self) -> bool:
        """Whether Nomad reports the job as running (not pending or dead)."""
        return self.status == "running"


class JobDeregisterResponse(NomadModel, frozen=True, kw_only=True):
    """The response from stopping a job (``DELETE /v1/job/:id``)."""

    eval_id: str = msgspec.field(name="EvalID", default="")
    eval_create_index: int = 0
    job_modify_index: int = 0


class JobRegisterResponse(JobDeregisterResponse, frozen=True, kw_only=True):
    """The response from registering a job (``POST /v1/jobs``).

    Carries the same eval/index fields as the deregister response, plus any
    server-side warnings raised while accepting the job.
    """

    warnings: str = ""


class TaskLifecycleSpec(NomadModel, frozen=True, kw_only=True):
    """A task's ``lifecycle`` block in a job spec."""

    hook: str | None = None
    sidecar: bool | None = None


class TaskSpec(NomadModel, frozen=True, kw_only=True):
    """A task in a job spec, limited to the fields ``nd`` reads."""

    name: str
    lifecycle: TaskLifecycleSpec | None = None


class TaskGroupSpec(NomadModel, frozen=True, kw_only=True):
    """A task group in a job spec, limited to the fields ``nd`` reads."""

    name: str
    tasks_raw: list[TaskSpec] | None = msgspec.field(name="Tasks", default=None)

    @property
    def tasks(self) -> list[TaskSpec]:
        """The group's tasks in spec order, with a null list read as empty."""
        return self.tasks_raw or []


class JobSpec(NomadModel, frozen=True, kw_only=True):
    """A job spec, limited to the fields ``nd`` reads."""

    task_groups_raw: list[TaskGroupSpec] | None = msgspec.field(name="TaskGroups", default=None)

    @property
    def task_groups(self) -> list[TaskGroupSpec]:
        """The job's task groups in spec order, with a null list read as empty."""
        return self.task_groups_raw or []


class JobRegisterPayload(NomadModel, frozen=True, kw_only=True):
    """The ``{"Job": {...}}`` body that ``nomad job run -output`` emits for ``POST /v1/jobs``."""

    job: JobSpec | None = None
