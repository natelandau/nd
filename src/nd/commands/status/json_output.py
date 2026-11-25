"""The ``nd status --json`` document: a stable, script-facing view of a `StatusReport`.

The structs here are the JSON contract. They stay separate from the report classes so
an internal refactor cannot change what scripts and agents parse.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import msgspec

from nd.commands.status.report import correlate_nodes

if TYPE_CHECKING:
    from nd.commands.status.report import HostJobRow, HostPanel, StatusReport


class ClusterJson(msgspec.Struct, frozen=True, kw_only=True):
    """Where the cluster lives and which server leads it."""

    address: str
    ui_url: str
    region: str | None
    namespace: str | None
    leader: str | None


class ServerJson(msgspec.Struct, frozen=True, kw_only=True):
    """A Nomad server agent."""

    name: str
    address: str
    status: str
    version: str
    leader: bool


class NodeJson(msgspec.Struct, frozen=True, kw_only=True):
    """A machine: a client node, a server, or both. ``id`` is null for a server-only host."""

    id: str | None
    name: str
    address: str
    role: str
    status: str
    eligible: bool
    version: str
    active_allocations: int


class JobJson(msgspec.Struct, frozen=True, kw_only=True):
    """A job with nd's effective status (which can be ``degraded``) and Nomad's raw one."""

    id: str
    name: str
    type: str
    status: str
    nomad_status: str
    nodes: list[str]


class AllocationCountsJson(msgspec.Struct, frozen=True, kw_only=True):
    """Cluster-wide allocation counts, as the dashboard banner shows them."""

    running: int
    pending: int
    failed: int


class VolumeJson(msgspec.Struct, frozen=True, kw_only=True):
    """A host volume name and the nodes it is registered on."""

    name: str
    nodes: list[str]
    state: str


class DeploymentJson(msgspec.Struct, frozen=True, kw_only=True):
    """An active deployment."""

    id: str
    job_id: str
    job_version: int
    status: str


class EvaluationJson(msgspec.Struct, frozen=True, kw_only=True):
    """A blocked, pending, or otherwise stuck evaluation."""

    id: str
    job_id: str
    status: str
    triggered_by: str
    queued_allocations: int


class HostJobJson(msgspec.Struct, frozen=True, kw_only=True):
    """An allocation running on a host. ``started_at`` is null when Nomad has no start time."""

    id: str
    name: str
    type: str
    group: str
    status: str
    started_at: datetime | None


class HostJson(msgspec.Struct, frozen=True, kw_only=True):
    """A client node and the jobs placed on it."""

    id: str
    name: str
    address: str
    status: str
    eligible: bool
    version: str
    jobs: list[HostJobJson]


class StatusJson(msgspec.Struct, frozen=True, kw_only=True):
    """The whole ``nd status --json`` document. ``hosts`` is present only with ``--hosts``."""

    health: str
    cluster: ClusterJson
    servers: list[ServerJson]
    nodes: list[NodeJson]
    jobs: list[JobJson]
    allocations: AllocationCountsJson
    volumes: list[VolumeJson]
    deployments: list[DeploymentJson]
    problem_evaluations: list[EvaluationJson]
    hosts: list[HostJson] | msgspec.UnsetType = msgspec.UNSET


def build_status_json(
    report: StatusReport, host_panels: list[HostPanel] | None = None
) -> StatusJson:
    """Translate a status report into the JSON document scripts and agents read.

    Args:
        report: The computed cluster snapshot.
        host_panels: Per-host panels for ``--hosts``; None leaves the ``hosts`` key out.

    Returns:
        StatusJson: The document, ready for `print_json`.
    """
    nodes = [
        NodeJson(
            id=row.link_id,
            name=row.name,
            address=row.address,
            role=row.role,
            status=row.status,
            eligible=row.eligible,
            version=row.version,
            # Server-only hosts run no client agent, so they hold no allocations.
            active_allocations=report.node_alloc_counts.get(row.link_id, 0) if row.link_id else 0,
        )
        for row in correlate_nodes(report.nodes, report.servers)
    ]
    return StatusJson(
        health=report.health.value.lower(),
        cluster=ClusterJson(
            address=report.address,
            ui_url=report.ui_url,
            region=report.region,
            namespace=report.namespace,
            leader=report.leader_name,
        ),
        servers=[
            ServerJson(
                name=s.name, address=s.addr, status=s.status, version=s.version, leader=s.is_leader
            )
            for s in report.servers
        ],
        nodes=nodes,
        jobs=[
            JobJson(
                id=job.id,
                name=job.name,
                type=job.type,
                status=report.job_statuses[job.id],
                nomad_status=job.status,
                nodes=report.job_nodes.get(job.id, []),
            )
            for job in report.jobs
        ],
        allocations=AllocationCountsJson(
            running=report.allocs_running,
            pending=report.allocs_pending,
            failed=report.allocs_failed,
        ),
        volumes=[VolumeJson(name=v.name, nodes=v.nodes, state=v.state) for v in report.volume_rows],
        deployments=[
            DeploymentJson(id=d.id, job_id=d.job_id, job_version=d.job_version, status=d.status)
            for d in report.deployments_active
        ],
        problem_evaluations=[
            EvaluationJson(
                id=e.id,
                job_id=e.job_id,
                status=e.status,
                triggered_by=e.triggered_by,
                queued_allocations=sum(e.queued_allocations.values()),
            )
            for e in report.evals_problem
        ],
        hosts=msgspec.UNSET if host_panels is None else [_host_json(h) for h in host_panels],
    )


def _host_json(host: HostPanel) -> HostJson:
    """Translate one host panel into its JSON form."""
    return HostJson(
        id=host.link_id,
        name=host.name,
        address=host.address,
        status=host.status,
        eligible=host.eligible,
        version=host.version,
        jobs=[_host_job_json(row) for row in host.jobs],
    )


def _host_job_json(row: HostJobRow) -> HostJobJson:
    """Translate one host job row, turning the nanosecond start anchor into a UTC time."""
    started_at = None
    if row.run_start_ns > 0:
        # Integer math, because a float of unix nanoseconds cannot hold every microsecond.
        seconds, nanos = divmod(row.run_start_ns, 10**9)
        started_at = datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=nanos // 1000)
    return HostJobJson(
        id=row.job_id,
        name=row.name,
        type=row.job_type,
        group=row.group,
        status=row.status,
        started_at=started_at,
    )
