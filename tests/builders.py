"""Builders for Nomad API models with valid defaults, so a test names only the fields it checks.

Pass a built model through `to_payload` to get the JSON body the Nomad API would send, for
mocked routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import msgspec

from nd.nomad.models.agent import AgentMember
from nd.nomad.models.allocation import AllocListStub, TaskState
from nd.nomad.models.deployment import Deployment, TaskGroupDeploymentState
from nd.nomad.models.evaluation import EvalListStub
from nd.nomad.models.job import JobListStub
from nd.nomad.models.node import Node, NodeListStub
from nd.nomad.models.volume import HostVolumeListStub

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
    submit_time: int = 0,
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
        submit_time=submit_time,
        create_index=1,
        modify_index=2,
    )


def task_state(
    state: str = "running", *, failed: bool = False, restarts: int = 0, started_at: str = ""
) -> TaskState:
    """Build one task's state within an allocation.

    Returns:
        TaskState: The task state.
    """
    return TaskState(state=state, failed=failed, restarts=restarts, started_at_raw=started_at)


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
        create_index=1,
        modify_index=2,
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
