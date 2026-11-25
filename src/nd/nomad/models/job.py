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
    # The periodic or parameterized job that launched this one; empty for a job defined
    # by a file.
    parent_id_raw: str | None = msgspec.field(name="ParentID", default=None)
    create_index: int
    modify_index: int

    @property
    def is_child(self) -> bool:
        """Whether a periodic or parameterized job launched this one.

        A child has no file of its own and runs its parent's spec, so per-file and
        per-spec checks skip it.
        """
        return bool(self.parent_id_raw)

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

    @property
    def is_short_lived(self) -> bool:
        """Whether the task runs to completion around the main task instead of beside it."""
        return self.hook is not None and not self.sidecar


class ServiceCheckSpec(NomadModel, frozen=True, kw_only=True):
    """One health check on a service; nd only counts them."""


class ServiceSpec(NomadModel, frozen=True, kw_only=True):
    """A service registered by a task group or a task."""

    name: str | None = None
    checks_raw: list[ServiceCheckSpec] | None = msgspec.field(name="Checks", default=None)

    @property
    def checks(self) -> list[ServiceCheckSpec]:
        """The service's health checks, with a null list read as empty."""
        return self.checks_raw or []


class TaskResourcesSpec(NomadModel, frozen=True, kw_only=True):
    """A task's reserved CPU and memory; None when compiled output leaves one unset."""

    cpu: int | None = msgspec.field(name="CPU", default=None)
    memory_mb: int | None = msgspec.field(name="MemoryMB", default=None)


class VolumeRequestSpec(NomadModel, frozen=True, kw_only=True):
    """A task group's request for a volume, naming the volume in ``source``."""

    type: str | None = None
    source: str | None = None
    # Nomad appends the allocation index to ``source``, so allocation 0 claims ``data[0]``.
    per_alloc: bool | None = None


class TaskSpec(NomadModel, frozen=True, kw_only=True):
    """A task in a job spec, limited to the fields ``nd`` reads."""

    name: str
    # Driver-specific settings (such as ``image``), so the keys vary by driver.
    config_raw: dict[str, object] | None = msgspec.field(name="Config", default=None)
    resources: TaskResourcesSpec | None = None
    lifecycle: TaskLifecycleSpec | None = None
    services_raw: list[ServiceSpec] | None = msgspec.field(name="Services", default=None)

    @property
    def config(self) -> dict[str, object]:
        """The task's driver config, with a null map read as empty."""
        return self.config_raw or {}

    @property
    def services(self) -> list[ServiceSpec]:
        """The services the task registers, with a null list read as empty."""
        return self.services_raw or []


class TaskGroupSpec(NomadModel, frozen=True, kw_only=True):
    """A task group in a job spec, limited to the fields ``nd`` reads."""

    name: str
    tasks_raw: list[TaskSpec] | None = msgspec.field(name="Tasks", default=None)
    services_raw: list[ServiceSpec] | None = msgspec.field(name="Services", default=None)
    volumes_raw: dict[str, VolumeRequestSpec] | None = msgspec.field(name="Volumes", default=None)

    @property
    def tasks(self) -> list[TaskSpec]:
        """The group's tasks in spec order, with a null list read as empty."""
        return self.tasks_raw or []

    @property
    def services(self) -> list[ServiceSpec]:
        """The services the group registers, with a null list read as empty."""
        return self.services_raw or []

    @property
    def volumes(self) -> dict[str, VolumeRequestSpec]:
        """The group's volume requests keyed by request name, with a null map read as empty."""
        return self.volumes_raw or {}


class JobSpec(NomadModel, frozen=True, kw_only=True):
    """A job spec, limited to the fields ``nd`` reads.

    Decodes both a registered job (``GET /v1/job/:job_id``) and the compiled body of
    ``nomad job run -output``, which share one shape. Compiled output sends an explicit
    null for every value the file leaves unset, which msgspec defaults do not cover, so
    every optional scalar here accepts None.
    """

    id: str = msgspec.field(name="ID", default="")
    name: str = ""
    # Null in compiled output, which has no run state yet.
    status: str | None = None
    task_groups_raw: list[TaskGroupSpec] | None = msgspec.field(name="TaskGroups", default=None)

    @property
    def task_groups(self) -> list[TaskGroupSpec]:
        """The job's task groups in spec order, with a null list read as empty."""
        return self.task_groups_raw or []

    @property
    def is_dead(self) -> bool:
        """Whether Nomad reports the job as stopped."""
        return self.status == "dead"


class JobRegisterPayload(NomadModel, frozen=True, kw_only=True):
    """The ``{"Job": {...}}`` body that ``nomad job run -output`` emits for ``POST /v1/jobs``."""

    job: JobSpec | None = None
