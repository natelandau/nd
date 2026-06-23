"""Pure aggregation for ``nd status``: turn raw Nomad listings into a `StatusReport`.

Kept free of I/O and Rich so the cluster-state logic is unit-testable on its own;
`render.py` consumes the report and `command.py` feeds it the live listings.
"""

from __future__ import annotations

import enum
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nd.constants import HEALTHY_ALLOC_STATUSES

if TYPE_CHECKING:
    from nd.nomad.config import NomadConfig
    from nd.nomad.models.agent import AgentMember
    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.deployment import DeploymentListStub
    from nd.nomad.models.evaluation import EvalListStub
    from nd.nomad.models.job import JobListStub
    from nd.nomad.models.node import NodeListStub

# Allocation client statuses that represent live work (counted in the per-node/per-job columns).
_ACTIVE_ALLOC_STATUSES = frozenset({"running", "pending"})
# Deployment statuses that represent an in-progress (notable) rollout.
_ACTIVE_DEPLOYMENT_STATUSES = frozenset({"running", "pending", "blocked", "paused", "unblocking"})
# Evaluation statuses that indicate the scheduler is stuck.
_PROBLEM_EVAL_STATUSES = frozenset({"blocked", "pending"})
# Terminal evaluation statuses whose queued-allocation counts are historical, not live.
_TERMINAL_EVAL_STATUSES = frozenset({"complete", "canceled", "cancelled", "failed"})


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
class StatusReport:
    """A fully computed snapshot of cluster state, ready for rendering."""

    health: Health
    address: str
    ui_url: str
    region: str | None
    namespace: str | None
    servers: list[ServerInfo]
    servers_alive: int
    servers_total: int
    leader_name: str | None
    nodes: list[NodeListStub]
    nodes_ready: int
    nodes_total: int
    jobs: list[JobListStub]
    jobs_total: int
    jobs_running: int
    allocs_total: int
    allocs_running: int
    allocs_failed: int
    allocs_pending: int
    node_alloc_counts: dict[str, int]  # active alloc count, keyed by node id
    job_nodes: dict[str, list[str]]  # sorted node names an active alloc lives on, keyed by job id
    deployments_active: list[DeploymentListStub]
    evals_problem: list[EvalListStub]


def build_report(  # noqa: PLR0913
    *,
    nodes: list[NodeListStub],
    jobs: list[JobListStub],
    allocs: list[AllocListStub],
    config: NomadConfig,
    members: list[AgentMember] | None = None,
    leader: str | None = None,
    deployments: list[DeploymentListStub] | None = None,
    evals: list[EvalListStub] | None = None,
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

    allocs_failed = sum(1 for a in allocs if a.client_status == "failed")
    allocs_pending = sum(1 for a in allocs if a.client_status == "pending")
    allocs_unhealthy = any(a.client_status not in HEALTHY_ALLOC_STATUSES for a in allocs)
    node_alloc_counts = Counter(
        a.node_id for a in allocs if a.client_status in _ACTIVE_ALLOC_STATUSES
    )
    job_nodes = _job_node_names(allocs, nodes)

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
        servers_total=len(servers),
        leader_name=leader_name,
        nodes=nodes,
        nodes_ready=sum(1 for n in nodes if n.status == "ready"),
        nodes_total=len(nodes),
        jobs=jobs,
        jobs_total=len(jobs),
        jobs_running=sum(1 for j in jobs if j.status == "running"),
        allocs_total=len(allocs),
        allocs_running=sum(1 for a in allocs if a.client_status == "running"),
        allocs_failed=allocs_failed,
        allocs_pending=allocs_pending,
        node_alloc_counts=node_alloc_counts,
        job_nodes=job_nodes,
        deployments_active=deployments_active,
        evals_problem=evals_problem,
    )


def _job_node_names(allocs: list[AllocListStub], nodes: list[NodeListStub]) -> dict[str, list[str]]:
    """Map each job id to the sorted, de-duplicated names of nodes its active allocs run on.

    Only running/pending allocations count, so the column reflects live placement rather than
    the historical pile of terminal allocs. Node ids are resolved to display names, falling
    back to a short id when a node is unknown.
    """
    node_names = {node.id: node.name for node in nodes}
    job_node_sets: dict[str, set[str]] = {}
    for alloc in allocs:
        if alloc.client_status not in _ACTIVE_ALLOC_STATUSES:
            continue
        name = node_names.get(alloc.node_id, alloc.node_id[:8])
        job_node_sets.setdefault(alloc.job_id, set()).add(name)
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
    node_degraded = any(n.drain or n.scheduling_eligibility != "eligible" for n in nodes)
    jobs_degraded = any(j.status != "running" for j in jobs)
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
        eligible=node.scheduling_eligibility == "eligible" and not node.drain,
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
