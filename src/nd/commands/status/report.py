"""Pure aggregation for ``nd status``: turn raw Nomad listings into a `StatusReport`.

Kept free of I/O and Rich so the cluster-state logic is unit-testable on its own;
`render.py` consumes the report and `command.py` feeds it the live listings.
"""

from __future__ import annotations

import enum
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nd.commands.volume.report import volume_node_labels
from nd.constants import FAILED_ALLOC_STATUSES, HEALTHY_ALLOC_STATUSES
from nd.nodes import node_label

if TYPE_CHECKING:
    from nd.nomad.config import NomadConfig
    from nd.nomad.models.agent import AgentMember
    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.deployment import Deployment
    from nd.nomad.models.evaluation import EvalListStub
    from nd.nomad.models.job import JobListStub
    from nd.nomad.models.node import NodeListStub
    from nd.nomad.models.volume import HostVolumeListStub

# Allocation client statuses that represent live work (counted in the per-node/per-job columns).
_ACTIVE_ALLOC_STATUSES = frozenset({"running", "pending"})
# Deployment statuses that represent an in-progress (notable) rollout.
_ACTIVE_DEPLOYMENT_STATUSES = frozenset({"running", "pending", "blocked", "paused", "unblocking"})
# Evaluation statuses that indicate the scheduler is stuck.
_PROBLEM_EVAL_STATUSES = frozenset({"blocked", "pending"})
# Terminal evaluation statuses whose queued-allocation counts are historical, not live.
_TERMINAL_EVAL_STATUSES = frozenset({"complete", "canceled", "cancelled", "failed"})


def _alloc_run_start_ns(alloc: AllocListStub) -> int:
    """Return the nanosecond anchor for how long an allocation has been running.

    Prefers the earliest task ``StartedAt`` (when the alloc came up), falling back to the
    alloc's ``CreateTime`` when no task has a usable start time yet.
    """
    starts = [ns for task in alloc.task_states.values() if (ns := task.started_at_ns) > 0]
    return min(starts) if starts else alloc.create_time


class Health(enum.StrEnum):
    """Overall cluster health verdict."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class ServerInfo:
    """A Nomad server (control-plane) member, with leadership resolved."""

    name: str
    addr: str
    status: str
    version: str
    is_leader: bool


@dataclass(frozen=True)
class NodeRow:
    """A unified machine row combining a client node with any server role."""

    name: str
    address: str
    role: str  # "leader" | "server" | "client"
    role_healthy: bool  # serf status alive (always True for plain clients)
    status: str  # client node status, or the serf status for server-only hosts
    eligible: bool
    version: str
    link_id: str | None  # node id for the web UI link; None for server-only hosts


@dataclass(frozen=True)
class VolumeStatusRow:
    """One aggregated row in the Volumes panel: one row per distinct volume name."""

    name: str
    nodes: list[str]  # sorted node NAMES the volume is registered on
    state: str  # distinct states, comma-joined (usually "ready")


@dataclass(frozen=True)
class HostJobRow:
    """One allocation running on a host, as shown in a host panel's Jobs sub-table."""

    job_id: str
    name: str
    job_type: str
    group: str  # the allocation's task group
    status: str  # the allocation's client_status
    run_start_ns: int  # uptime anchor (earliest task start, else alloc create time), in unix nanos


@dataclass(frozen=True)
class HostPanel:
    """A single client node's slice of cluster state for the ``--hosts`` view."""

    name: str
    link_id: str  # node id for the web UI link
    address: str
    status: str
    eligible: bool  # scheduling-eligible and not draining
    version: str
    jobs: list[HostJobRow]


@dataclass(frozen=True)
class StatusReport:
    """A fully computed snapshot of cluster state, ready for rendering."""

    health: Health
    address: str
    ui_url: str
    region: str | None
    namespace: str | None
    servers: list[ServerInfo]
    servers_alive: int
    leader_name: str | None
    nodes: list[NodeListStub]
    nodes_ready: int
    jobs: list[JobListStub]
    jobs_running: int
    job_statuses: dict[str, str]  # effective display status keyed by job id (may be "degraded")
    allocs_running: int
    allocs_failed: int
    allocs_pending: int
    node_alloc_counts: dict[str, int]  # active alloc count, keyed by node id
    job_nodes: dict[str, list[str]]  # sorted node names an active alloc lives on, keyed by job id
    deployments_active: list[Deployment]
    evals_problem: list[EvalListStub]
    volume_rows: list[VolumeStatusRow]  # one row per distinct volume name, aggregated

    @property
    def servers_total(self) -> int:
        """Count the server members, the denominator of the servers-alive summary."""
        return len(self.servers)

    @property
    def nodes_total(self) -> int:
        """Count the client nodes, the denominator of the nodes-ready summary."""
        return len(self.nodes)

    @property
    def jobs_total(self) -> int:
        """Count the jobs, the denominator of the jobs-running summary."""
        return len(self.jobs)

    @property
    def volumes_total(self) -> int:
        """Count distinct volume names, not per-node registrations."""
        return len(self.volume_rows)


def build_report(  # noqa: PLR0913
    *,
    nodes: list[NodeListStub],
    jobs: list[JobListStub],
    allocs: list[AllocListStub],
    config: NomadConfig,
    members: list[AgentMember] | None = None,
    leader: str | None = None,
    deployments: list[Deployment] | None = None,
    evals: list[EvalListStub] | None = None,
    volumes: list[HostVolumeListStub] | None = None,
) -> StatusReport:
    """Compute a `StatusReport` from raw Nomad listings.

    Lists are sorted alphabetically by name. Kept free of I/O and Rich so the
    aggregation logic is unit-testable on its own.
    """
    nodes = sorted(nodes, key=lambda n: n.name)
    jobs = sorted(jobs, key=lambda j: j.name)
    servers = sorted(_build_servers(members or [], leader or ""), key=lambda s: s.name)
    leader_name = next((s.name for s in servers if s.is_leader), None)

    deployments_active = sorted(
        (d for d in (deployments or []) if d.status in _ACTIVE_DEPLOYMENT_STATUSES),
        key=lambda d: d.job_id,
    )
    evals_problem = sorted(
        (e for e in (evals or []) if _is_problem_eval(e)),
        key=lambda e: e.job_id,
    )

    # Only allocs Nomad still wants running reflect current health, so drop the ones it has
    # intentionally retired (desired_status stop/evict). A failed corpse that was rescheduled
    # keeps desired_status "run" and survives this filter; it is instead excluded per-check via
    # is_replaced, whose next_allocation points at the now-live replacement.
    live_allocs = [a for a in allocs if not a.is_retired]
    allocs_failed = sum(1 for a in live_allocs if a.client_status == "failed" and not a.is_replaced)
    allocs_pending = sum(1 for a in live_allocs if a.client_status == "pending")
    allocs_unhealthy = any(
        a.client_status not in HEALTHY_ALLOC_STATUSES and not a.is_replaced for a in live_allocs
    )
    node_alloc_counts = Counter(
        a.node_id for a in allocs if a.client_status in _ACTIVE_ALLOC_STATUSES
    )
    node_names = {node.id: node.name for node in nodes}
    job_nodes = _job_node_names(allocs=allocs, node_names=node_names)
    job_statuses = _job_display_statuses(jobs, live_allocs)
    volume_rows = _build_volume_rows(volumes=volumes or [], node_names=node_names)

    return StatusReport(
        health=_assess_health(
            nodes=nodes,
            jobs=jobs,
            servers=servers,
            leader_name=leader_name,
            allocs_unhealthy=allocs_unhealthy,
            evals_problem=evals_problem,
        ),
        address=config.address,
        ui_url=config.ui_base,
        region=config.region,
        namespace=config.namespace,
        servers=servers,
        servers_alive=sum(1 for s in servers if s.status == "alive"),
        leader_name=leader_name,
        nodes=nodes,
        nodes_ready=sum(1 for n in nodes if n.status == "ready"),
        jobs=jobs,
        jobs_running=sum(1 for j in jobs if job_statuses[j.id] == "running"),
        job_statuses=job_statuses,
        allocs_running=sum(1 for a in allocs if a.client_status == "running"),
        allocs_failed=allocs_failed,
        allocs_pending=allocs_pending,
        node_alloc_counts=node_alloc_counts,
        job_nodes=job_nodes,
        deployments_active=deployments_active,
        evals_problem=evals_problem,
        volume_rows=volume_rows,
    )


def build_host_report(
    *,
    nodes: list[NodeListStub],
    jobs: list[JobListStub],
    allocs: list[AllocListStub],
) -> list[HostPanel]:
    """Compute one `HostPanel` per client node for the ``--hosts`` view.

    Pivots the cluster snapshot to focus on machines: each panel carries the notable
    allocations placed on its node (running/pending plus genuine unreplaced failures, the
    same allocs the default view treats as live). Kept pure and Rich-free so the grouping
    logic is unit-testable on its own.
    """
    jobs_by_id = {job.id: job for job in jobs}
    allocs_by_node: dict[str, list[AllocListStub]] = {}
    for alloc in allocs:
        if _is_host_job_alloc(alloc):
            allocs_by_node.setdefault(alloc.node_id, []).append(alloc)

    panels: list[HostPanel] = []
    for node in sorted(nodes, key=lambda n: n.name):
        job_rows = sorted(
            (
                _host_job_row(alloc, jobs_by_id.get(alloc.job_id))
                for alloc in allocs_by_node.get(node.id, [])
            ),
            key=lambda r: (r.name, r.group),
        )
        panels.append(
            HostPanel(
                name=node.name,
                link_id=node.id,
                address=node.address,
                status=node.status,
                eligible=node.is_eligible,
                version=node.version,
                jobs=job_rows,
            )
        )
    return panels


def _is_host_job_alloc(alloc: AllocListStub) -> bool:
    """Return True when an allocation belongs in a host panel's Jobs sub-table.

    Mirrors the default view's live-allocation rules: drop the ones Nomad has retired
    (desired_status stop/evict) or already replaced, then keep the active work
    (running/pending) plus a genuine failure (failed/lost) that has not recovered.
    """
    if alloc.is_retired or alloc.is_replaced:
        return False
    return (
        alloc.client_status in _ACTIVE_ALLOC_STATUSES
        or alloc.client_status in FAILED_ALLOC_STATUSES
    )


def _host_job_row(alloc: AllocListStub, job: JobListStub | None) -> HostJobRow:
    """Build a host panel Jobs row, resolving the job's display name and type."""
    return HostJobRow(
        job_id=alloc.job_id,
        name=job.name if job else alloc.job_id,
        job_type=job.type if job else "",
        group=alloc.task_group,
        status=alloc.client_status,
        run_start_ns=_alloc_run_start_ns(alloc),
    )


def _build_volume_rows(
    *, volumes: list[HostVolumeListStub], node_names: dict[str, str]
) -> list[VolumeStatusRow]:
    """Aggregate per-registration volume stubs into one row per distinct volume name.

    Node IDs resolve to display names so the panel shows hostnames rather than GUIDs.
    """
    states: dict[str, set[str]] = {}
    for vol in volumes:
        if vol.state:
            states.setdefault(vol.name, set()).add(vol.state)
    labels = volume_node_labels(registered=volumes, node_names=node_names)
    return [
        VolumeStatusRow(
            name=name,
            nodes=nodes,
            state=", ".join(sorted(states.get(name, ()))) or "-",
        )
        for name, nodes in sorted(labels.items())
    ]


def _job_display_statuses(
    jobs: list[JobListStub], live_allocs: list[AllocListStub]
) -> dict[str, str]:
    """Map each job id to the status to display, downgrading a real partial outage to "degraded".

    Nomad's job-level ``Status`` stays "running" for a service/system job even when its latest
    allocation on a node has failed (e.g. a system job that can't start on one node), so the raw
    status hides the outage. A job is "degraded" only when it has a genuinely-stuck placement: a
    ``failed``/``lost`` alloc that Nomad still wants running (not intentionally stopped) and has
    NOT replaced (see ``AllocListStub.is_replaced``), so a failure that already recovered does not read as
    degraded.
    """
    degraded_jobs = {
        a.job_id
        for a in live_allocs
        if a.client_status in FAILED_ALLOC_STATUSES and not a.is_replaced
    }
    return {
        job.id: "degraded" if job.is_running and job.id in degraded_jobs else job.status
        for job in jobs
    }


def _job_node_names(
    *, allocs: list[AllocListStub], node_names: dict[str, str]
) -> dict[str, list[str]]:
    """Map each job id to the sorted, de-duplicated names of nodes its active allocs run on.

    Only running/pending allocations count, so the column reflects live placement rather than
    the historical pile of terminal allocs.
    """
    job_node_sets: dict[str, set[str]] = {}
    for alloc in allocs:
        if alloc.client_status in _ACTIVE_ALLOC_STATUSES:
            job_node_sets.setdefault(alloc.job_id, set()).add(
                node_label(node_names=node_names, node_id=alloc.node_id)
            )
    return {job_id: sorted(names) for job_id, names in job_node_sets.items()}


def _build_servers(members: list[AgentMember], leader: str) -> list[ServerInfo]:
    """Convert serf members into `ServerInfo`, resolving which one is the leader."""
    return [
        ServerInfo(
            name=member.name.split(".")[0],
            addr=member.addr,
            status=member.status,
            version=member.tags.get("build", ""),
            is_leader=_member_is_leader(member, leader),
        )
        for member in members
    ]


def _member_is_leader(member: AgentMember, leader: str) -> bool:
    """Match a member against the leader's RPC address from ``/v1/status/leader``.

    Nomad reports the leader by its RPC advertise address (``host:port``), which a
    member exposes via its ``rpc_addr``/``port`` tags. Those can differ from the
    serf gossip ``addr``, so prefer the tags and only fall back to the serf host.
    """
    if not leader:
        return False
    rpc_addr = member.tags.get("rpc_addr")
    port = member.tags.get("port")
    if rpc_addr and port and leader == f"{rpc_addr}:{port}":
        return True
    return member.addr == leader.split(":", maxsplit=1)[0]


def _is_problem_eval(evaluation: EvalListStub) -> bool:
    """Return True when an evaluation is actively stuck (blocked/pending or queued).

    Queued allocations on a terminal evaluation are historical, not a live problem.
    """
    if evaluation.status in _PROBLEM_EVAL_STATUSES:
        return True
    if evaluation.status in _TERMINAL_EVAL_STATUSES:
        return False
    return any(count > 0 for count in evaluation.queued_allocations.values())


def _assess_health(
    *,
    nodes: list[NodeListStub],
    jobs: list[JobListStub],
    servers: list[ServerInfo],
    leader_name: str | None,
    allocs_unhealthy: bool,
    evals_problem: list[EvalListStub],
) -> Health:
    """Derive the overall health verdict from cluster state."""
    if any(n.status == "down" for n in nodes):
        return Health.CRITICAL
    if servers and leader_name is None:  # have servers but no elected leader
        return Health.CRITICAL
    node_degraded = any(not n.is_eligible for n in nodes)
    jobs_degraded = any(not j.is_running for j in jobs)
    servers_degraded = any(s.status != "alive" for s in servers)
    if node_degraded or jobs_degraded or servers_degraded or allocs_unhealthy or evals_problem:
        return Health.DEGRADED
    return Health.HEALTHY


def correlate_nodes(nodes: list[NodeListStub], servers: list[ServerInfo]) -> list[NodeRow]:
    """Merge client nodes and server members into one role-annotated list.

    A server is matched to a client node by serf address or by host name (the serf
    addr and the node's HTTP address are distinct fields that need not be equal);
    any server without a backing client node is appended so nothing is hidden.
    """
    by_addr = {s.addr: s for s in servers if s.addr}
    by_name = {s.name: s for s in servers}
    pairs = [(node, by_addr.get(node.address) or by_name.get(node.name)) for node in nodes]
    rows = [_node_row(node, server) for node, server in pairs]
    matched = {server.name for _node, server in pairs if server is not None}
    rows.extend(_server_only_row(s) for s in servers if s.name not in matched)
    return sorted(rows, key=lambda r: r.name)


def _node_row(node: NodeListStub, server: ServerInfo | None) -> NodeRow:
    """Build a node row, folding in a server role when the host is also a server."""
    role = "client" if server is None else ("leader" if server.is_leader else "server")
    return NodeRow(
        name=node.name,
        address=node.address,
        role=role,
        role_healthy=server is None or server.status == "alive",
        status=node.status,
        eligible=node.is_eligible,
        version=node.version,
        link_id=node.id,
    )


def _server_only_row(server: ServerInfo) -> NodeRow:
    """Build a row for a server that has no backing client node."""
    return NodeRow(
        name=server.name,
        address=server.addr,
        role="leader" if server.is_leader else "server",
        role_healthy=server.status == "alive",
        status=server.status,
        eligible=False,
        version=server.version,
        link_id=None,
    )
