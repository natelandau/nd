"""Builders for Nomad API models with valid defaults, so a test names only the fields it checks.

Pass a built model through `to_payload` to get the JSON body the Nomad API would send, for
mocked routes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import msgspec

from nd.commands.doctor.findings import DoctorSnapshot, JobDrift
from nd.nomad.models.agent import AgentMember
from nd.nomad.models.allocation import (
    AllocDeploymentStatus,
    AllocListStub,
    TaskEvent,
    TaskState,
)
from nd.nomad.models.deployment import Deployment, TaskGroupDeploymentState
from nd.nomad.models.evaluation import EvalListStub
from nd.nomad.models.job import (
    JobDiff,
    JobListStub,
    JobPlanResponse,
    JobRegisterPayload,
    JobRegisterResponse,
    JobSpec,
    ServiceSpec,
    TaskDiff,
    TaskGroupDiff,
    TaskGroupSpec,
    TaskLifecycleSpec,
    TaskResourcesSpec,
    TaskSpec,
    VolumeRequestSpec,
)
from nd.nomad.models.node import Node, NodeListStub
from nd.nomad.models.volume import HostVolumeListStub
from nd.volumefiles import VolumeSpec

if TYPE_CHECKING:
    from nd.nomad.models import NomadModel


def to_payload(model: NomadModel) -> dict[str, object]:
    """Encode a model as the PascalCase JSON object the Nomad API returns for it.

    Returns:
        dict[str, object]: The model's fields under their Nomad wire names.
    """
    payload = msgspec.to_builtins(model)
    if not isinstance(payload, dict):
        msg = f"Expected {type(model).__name__} to encode as a JSON object, got {payload!r}"
        raise TypeError(msg)
    return payload


def job_stub(
    name: str = "web",
    *,
    status: str = "running",
    job_type: str = "service",
    parent_id: str = "",
    namespace: str = "default",
) -> JobListStub:
    """Build a job list entry whose ID equals its name.

    Returns:
        JobListStub: The job.
    """
    return JobListStub(
        id=name,
        name=name,
        type=job_type,
        status=status,
        priority=50,
        namespace=namespace,
        parent_id_raw=parent_id,
        create_index=1,
        modify_index=2,
    )


def task_state(
    state: str = "running",
    *,
    failed: bool = False,
    started_at: str = "",
    restarts: int = 0,
    last_restart: str = "",
    events: list[TaskEvent] | None = None,
) -> TaskState:
    """Build one task's state within an allocation.

    Returns:
        TaskState: The task state.
    """
    return TaskState(
        state=state,
        failed=failed,
        restarts=restarts,
        started_at_raw=started_at,
        last_restart_raw=last_restart,
        events_raw=events,
    )


def task_event(event_type: str = "Terminated", message: str = "Exit Code: 1") -> TaskEvent:
    """Build one task event.

    Returns:
        TaskEvent: The event.
    """
    return TaskEvent(type=event_type, display_message=message)


def task_spec(
    name: str = "app",
    *,
    image: str | None = "nginx:1.27",
    cpu: int = 500,
    memory_mb: int = 512,
    services: list[ServiceSpec] | None = None,
    lifecycle: TaskLifecycleSpec | None = None,
) -> TaskSpec:
    """Build a task; pass `image=None` for a task whose config has no image.

    Returns:
        TaskSpec: The task.
    """
    return TaskSpec(
        name=name,
        config_raw={} if image is None else {"image": image},
        resources=TaskResourcesSpec(cpu=cpu, memory_mb=memory_mb),
        lifecycle=lifecycle,
        services_raw=services,
    )


def task_group_spec(
    name: str = "web",
    *,
    tasks: list[TaskSpec] | None = None,
    services: list[ServiceSpec] | None = None,
    volumes: dict[str, VolumeRequestSpec] | None = None,
) -> TaskGroupSpec:
    """Build a task group; with no tasks given it holds one default `task_spec()`.

    Returns:
        TaskGroupSpec: The task group.
    """
    return TaskGroupSpec(
        name=name,
        tasks_raw=[task_spec()] if tasks is None else tasks,
        services_raw=services,
        volumes_raw=volumes,
    )


def volume_request(
    source: str = "data", *, request_type: str = "host", per_alloc: bool = False
) -> VolumeRequestSpec:
    """Build a task group's request for the named volume.

    Returns:
        VolumeRequestSpec: The volume request.
    """
    return VolumeRequestSpec(type=request_type, source=source, per_alloc=per_alloc)


def job_spec(
    name: str = "web",
    *,
    status: str = "running",
    groups: list[TaskGroupSpec] | None = None,
    tasks: list[TaskSpec] | None = None,
    volumes: dict[str, VolumeRequestSpec] | None = None,
) -> JobSpec:
    """Build a full job spec whose ID equals its name.

    With no groups given it holds one `task_group_spec()` built from `tasks` and `volumes`.

    Returns:
        JobSpec: The job spec.

    Raises:
        ValueError: If `groups` is given together with `tasks` or `volumes`.
    """
    if groups is not None and (tasks is not None or volumes is not None):
        msg = f"Expected groups, or tasks and volumes, not both (groups={groups!r})"
        raise ValueError(msg)
    return JobSpec(
        id=name,
        name=name,
        status=status,
        task_groups_raw=[task_group_spec(tasks=tasks, volumes=volumes)]
        if groups is None
        else groups,
    )


def compiled_job(job_id: str = "web") -> bytes:
    """Build the `{"Job": {...}}` body that `nomad job run -output` emits for a job.

    Returns:
        bytes: The compiled job JSON.
    """
    return msgspec.json.encode(JobRegisterPayload(job=job_spec(job_id)))


def task_group_diff(name: str = "app", *edited_tasks: str, type_: str = "Edited") -> TaskGroupDiff:
    """Build a plan diff of one task group whose listed tasks are edited.

    Returns:
        TaskGroupDiff: The group diff.
    """
    return TaskGroupDiff(
        name=name,
        type=type_,
        tasks_raw=[TaskDiff(name=task, type="Edited") for task in edited_tasks],
    )


def job_diff(*groups: TaskGroupDiff, type_: str = "Edited") -> JobDiff:
    """Build a job plan diff over the given group diffs.

    Returns:
        JobDiff: The job diff.
    """
    return JobDiff(type=type_, task_groups_raw=list(groups))


def job_plan(diff: JobDiff) -> dict[str, object]:
    """Build the plan endpoint's response body for a diff.

    Returns:
        dict[str, object]: The JSON body.
    """
    return to_payload(JobPlanResponse(diff=diff))


def alloc_stub(
    alloc_id: str = "a1",
    *,
    name: str = "",
    job_id: str = "web",
    task_group: str = "web",
    node_id: str = "n1",
    client_status: str = "running",
    desired_status: str = "run",
    next_allocation: str = "",
    create_time: int = 0,
    create_index: int = 1,
    modify_index: int = 2,
    job_version: int = 0,
    healthy: bool | None = None,
    task_states: dict[str, TaskState] | None = None,
) -> AllocListStub:
    """Build an allocation list entry; the name defaults to `<job_id>.<task_group>[0]`.

    Returns:
        AllocListStub: The allocation.
    """
    return AllocListStub(
        id=alloc_id,
        name=name or f"{job_id}.{task_group}[0]",
        node_id=node_id,
        job_id=job_id,
        task_group=task_group,
        client_status=client_status,
        desired_status=desired_status,
        next_allocation=next_allocation,
        task_states_raw=task_states,
        create_time=create_time,
        job_version=job_version,
        deployment_status=AllocDeploymentStatus(healthy=healthy),
        create_index=create_index,
        modify_index=modify_index,
    )


def node_stub(
    name: str = "node1",
    *,
    node_id: str = "",
    status: str = "ready",
    drain: bool = False,
    eligibility: str = "eligible",
    address: str = "10.0.0.1",
) -> NodeListStub:
    """Build a node list entry; the ID defaults to the name.

    Returns:
        NodeListStub: The node.
    """
    return NodeListStub(
        id=node_id or name,
        datacenter="dc1",
        name=name,
        node_class="",
        address=address,
        drain=drain,
        scheduling_eligibility=eligibility,
        status=status,
        version="1.9.0",
        create_index=1,
        modify_index=2,
    )


def node_detail(
    name: str = "node1",
    *,
    node_id: str = "n1",
    status: str = "ready",
    meta: dict[str, str] | None = None,
) -> Node:
    """Build a full node record, the shape `GET /v1/node/:id` returns.

    Returns:
        Node: The node.
    """
    return Node(
        id=node_id,
        datacenter="dc1",
        name=name,
        node_class="",
        status=status,
        drain=False,
        scheduling_eligibility="eligible",
        meta=meta or {},
        create_index=1,
        modify_index=2,
    )


def deployment(
    job_id: str = "web",
    *,
    status: str = "running",
    job_version: int = 0,
    task_groups: dict[str, TaskGroupDeploymentState] | None = None,
    create_index: int = 1,
    status_description: str = "",
) -> Deployment:
    """Build a deployment whose ID is `dep-<job_id>`.

    Returns:
        Deployment: The deployment.
    """
    return Deployment(
        id=f"dep-{job_id}",
        job_id=job_id,
        status=status,
        status_description=status_description,
        job_version=job_version,
        task_groups=task_groups or {},
        create_index=create_index,
        modify_index=2,
    )


def eval_stub(
    job_id: str = "web", *, status: str = "complete", queued: dict[str, int] | None = None
) -> EvalListStub:
    """Build an evaluation list entry whose ID is `eval-<job_id>`.

    Returns:
        EvalListStub: The evaluation.
    """
    return EvalListStub(
        id=f"eval-{job_id}",
        job_id=job_id,
        status=status,
        type="service",
        triggered_by="job-register",
        queued_allocations=queued or {},
        create_index=1,
        modify_index=2,
    )


def host_volume_stub(
    name: str = "data", *, node_id: str = "n1", volume_id: str = "", state: str = "ready"
) -> HostVolumeListStub:
    """Build a host volume list entry; the ID defaults to `<name>:<node_id>`.

    Returns:
        HostVolumeListStub: The volume.
    """
    return HostVolumeListStub(
        id=volume_id or f"{name}:{node_id}", name=name, node_id=node_id, state=state
    )


def agent_member(
    name: str = "server1.global",
    *,
    addr: str = "10.0.0.1",
    status: str = "alive",
    build: str = "2.0.3",
) -> AgentMember:
    """Build a server agent member.

    Returns:
        AgentMember: The member.
    """
    return AgentMember(name=name, addr=addr, status=status, tags={"build": build, "port": "4647"})


def register_response(
    *, eval_id: str = "e1", job_modify_index: int = 1, warnings: str = ""
) -> JobRegisterResponse:
    """Build the response Nomad returns for `POST /v1/jobs`.

    Returns:
        JobRegisterResponse: The response.
    """
    return JobRegisterResponse(
        eval_id=eval_id, job_modify_index=job_modify_index, warnings=warnings
    )


def volume_spec(name: str = "data", *, relative_path: str | None = None) -> VolumeSpec:
    """Build a host volume spec read from `/v/<name>.hcl`; the relative path defaults to the name.

    Returns:
        VolumeSpec: The spec.
    """
    return VolumeSpec(
        path=Path(f"/v/{name}.hcl"),
        name=name,
        capabilities=[{"access_mode": "single-node-writer", "attachment_mode": "file-system"}],
        relative_path=name if relative_path is None else relative_path,
    )


def doctor_snapshot(
    *,
    jobs: list[JobListStub] | None = None,
    job_specs: list[JobSpec] | None = None,
    allocs: list[AllocListStub] | None = None,
    nodes: list[NodeListStub] | None = None,
    members: list[AgentMember] | None = None,
    evals: list[EvalListStub] | None = None,
    volumes: list[HostVolumeListStub] | None = None,
    job_file_paths: dict[str, Path] | None = None,
    job_directories_configured: bool = True,
    unnamed_job_files: list[Path] | None = None,
    volume_spec_names: frozenset[str] = frozenset(),
    job_drift: dict[JobListStub, JobDrift] | None = None,
    drift_not_checked: str | None = None,
    now_ns: int = 0,
) -> DoctorSnapshot:
    """Build a cluster snapshot for nd doctor checks; every listing defaults to empty.

    Returns:
        DoctorSnapshot: The snapshot.
    """
    return DoctorSnapshot(
        jobs=jobs or [],
        job_specs=job_specs or [],
        allocs=allocs or [],
        nodes=nodes or [],
        members=members or [],
        evals=evals or [],
        volumes=volumes or [],
        job_file_paths=job_file_paths or {},
        job_directories_configured=job_directories_configured,
        unnamed_job_files=unnamed_job_files or [],
        volume_spec_names=volume_spec_names,
        job_drift=job_drift or {},
        drift_not_checked=drift_not_checked,
        now_ns=now_ns,
    )
