"""Models for the Nomad deployments endpoints."""

from __future__ import annotations

import msgspec


class _DeploymentCommon(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """Fields shared by the deployment list stub and the full deployment record."""

    id: str = msgspec.field(name="ID")
    job_id: str = msgspec.field(name="JobID")
    namespace: str = "default"
    status: str
    status_description: str = ""
    job_version: int = 0


class DeploymentListStub(_DeploymentCommon, frozen=True, kw_only=True):
    """A deployment as returned by ``GET /v1/deployments``."""

    create_index: int
    modify_index: int


class TaskGroupDeploymentState(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """Per-task-group rollout counts within a deployment."""

    desired_total: int = 0
    placed_allocs: int = 0
    healthy_allocs: int = 0
    unhealthy_allocs: int = 0


class Deployment(_DeploymentCommon, frozen=True, kw_only=True):
    """A deployment as returned by ``GET /v1/deployment/:id``."""

    task_groups: dict[str, TaskGroupDeploymentState] = msgspec.field(
        name="TaskGroups", default_factory=dict
    )
