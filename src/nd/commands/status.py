"""The ``nd status`` command: an at-a-glance Nomad cluster overview."""

from __future__ import annotations

import asyncio
import contextlib
import enum
import time
from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Annotated, Any, Protocol

import typer
from nclutils import pp
from nclutils.pp import Verbosity
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table

from nd.nomad import NomadClient, NomadConfig

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from rich.console import RenderableType

    from nd.nomad.models.agent import AgentMember
    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.deployment import DeploymentListStub
    from nd.nomad.models.evaluation import EvalListStub
    from nd.nomad.models.job import JobListStub
    from nd.nomad.models.node import NodeListStub

# Allocation client statuses that are considered healthy.
_HEALTHY_ALLOC_STATUSES = frozenset({"running", "complete"})
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
    allocs_unhealthy = any(a.client_status not in _HEALTHY_ALLOC_STATUSES for a in allocs)
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
        ui_url=(config.ui_url or config.address).rstrip("/"),
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


_HEALTH_STYLE: dict[Health, str] = {
    Health.HEALTHY: "green",
    Health.DEGRADED: "yellow",
    Health.CRITICAL: "red",
}

# Maps a Nomad status string to a Rich color used for its cell.
_STATUS_STYLE = {
    "ready": "green",
    "running": "green",
    "complete": "green",
    "alive": "green",
    "pending": "yellow",
    "initializing": "yellow",
    "draining": "yellow",
    "leaving": "yellow",
    "paused": "yellow",
    "blocked": "yellow",
    "down": "red",
    "dead": "red",
    "failed": "red",
    "lost": "red",
    "disconnected": "red",
}


def render_report(report: StatusReport) -> None:
    """Print the status report as a banner followed by the cluster panels."""
    console = pp.console()
    console.print(_banner(report))
    console.print(_nodes_panel(report))
    console.print(_jobs_panel(report))
    if report.deployments_active or report.evals_problem:
        console.print(_activity_panel(report))


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


def _node_url(ui_url: str, node_id: str) -> str:
    """Build the web UI URL for a client node."""
    return f"{ui_url}/ui/clients/{node_id}"


def _job_url(ui_url: str, job_id: str) -> str:
    """Build the web UI URL for a job."""
    return f"{ui_url}/ui/jobs/{job_id}"


def _link(url: str, text: str) -> str:
    """Wrap text in Rich link markup pointing at the given URL."""
    return f"[link={url}]{text}[/link]"


def _status_cell(status: str) -> str:
    """Render a status string as a colored glyph + label for a table cell."""
    style = _STATUS_STYLE.get(status, "default")
    glyph = {"green": "✓", "red": "✗"}.get(style, "•")
    return f"[{style}]{glyph} {status}[/]"


def _role_cell(row: NodeRow) -> str:
    """Render a node's cluster role, flagging an unhealthy server agent."""
    if row.role == "client":
        return "[dim]client[/]"
    label = "★ leader" if row.role == "leader" else "server"
    if not row.role_healthy:
        return f"[red]{label} (down)[/]"
    style = "magenta" if row.role == "leader" else "cyan"
    return f"[{style}]{label}[/]"


def _allocs_cell(row: NodeRow, counts: dict[str, int]) -> str:
    """Render a node's active-alloc count, dashing server-only hosts that hold none."""
    if row.link_id is None:
        return "[dim]-[/]"
    return str(counts.get(row.link_id, 0))


def _format_uptime(submit_time_ns: int, now_s: float) -> str:
    """Format a job's time-since-submit as a compact human duration."""
    if submit_time_ns <= 0:
        return "-"
    seconds = int(now_s - submit_time_ns / 1_000_000_000)
    if seconds < 0:
        return "-"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


def _banner_title(report: StatusReport) -> str:
    """Build the banner panel title from address, region, and namespace."""
    host = report.address.split("://")[-1]
    title = f"Nomad · {host}"
    if report.region:
        title += f" ({report.region})"
    if report.namespace:
        title += f" · {report.namespace}"
    return title


def _banner(report: StatusReport) -> Panel:
    """Build the top summary banner."""
    style = _HEALTH_STYLE[report.health]
    grid = Table.grid(padding=(0, 0))
    grid.add_row(f"[{style}]●[/] [bold {style}]{report.health.value}[/]")
    grid.add_row(
        f"Servers {report.servers_alive}/{report.servers_total} · "
        f"leader {report.leader_name or 'none'}   "
        f"Nodes {report.nodes_ready}/{report.nodes_total} ready"
    )
    grid.add_row(
        f"Jobs {report.jobs_running}/{report.jobs_total} running   "
        f"Allocs {report.allocs_running} running · "
        f"{report.allocs_failed} failed · {report.allocs_pending} pending"
    )
    grid.add_row(
        f"Deployments {len(report.deployments_active)} active   "
        f"Evals {len(report.evals_problem)} blocked"
    )
    return Panel(
        grid, title=_banner_title(report), title_align="left", border_style=style, expand=False
    )


def _table(*columns: str) -> Table:
    """Build a borderless status table with the given column headers."""
    table = Table(box=box.SIMPLE, expand=True, pad_edge=False)
    for column in columns:
        table.add_column(column)
    return table


def _panel(body: RenderableType, title: str, *, border_style: str = "cyan") -> Panel:
    """Wrap a renderable in a left-titled panel."""
    return Panel(body, title=title, title_align="left", border_style=border_style)


def _nodes_panel(report: StatusReport) -> Panel:
    """Build the combined nodes panel (clients + servers, role-annotated)."""
    rows = correlate_nodes(report.nodes, report.servers)
    if not rows:
        return _panel("[dim]No nodes[/]", "Nodes")
    table = _table("NAME", "ADDRESS", "ROLE", "ALLOCS", "STATUS", "ELIGIBLE", "VERSION")
    for row in rows:
        name = _link(_node_url(report.ui_url, row.link_id), row.name) if row.link_id else row.name
        eligible = (
            "[green]✓[/]" if row.eligible else ("[dim]-[/]" if row.link_id is None else "[red]✗[/]")
        )
        table.add_row(
            name,
            row.address,
            _role_cell(row),
            _allocs_cell(row, report.node_alloc_counts),
            _status_cell(row.status),
            eligible,
            row.version,
        )
    return _panel(table, "Nodes")


def _jobs_panel(report: StatusReport) -> Panel:
    """Build the jobs panel listing every job."""
    if not report.jobs:
        return _panel("[dim]No jobs[/]", "Jobs")
    now_s = time.time()
    table = _table("NAME", "TYPE", "STATUS", "UPTIME", "NODES")
    for job in report.jobs:
        nodes = report.job_nodes.get(job.id, [])
        table.add_row(
            _link(_job_url(report.ui_url, job.id), job.name),
            job.type,
            _status_cell(job.status),
            _format_uptime(job.submit_time, now_s),
            ", ".join(nodes) if nodes else "[dim]-[/]",
        )
    return _panel(table, "Jobs")


def _activity_panel(report: StatusReport) -> Panel:
    """Build the activity panel (rendered only when there is in-progress work)."""
    sections: list[RenderableType] = []
    if report.deployments_active:
        table = _table("JOB", "VERSION", "STATUS")
        for dep in report.deployments_active:
            table.add_row(dep.job_id, str(dep.job_version), _status_cell(dep.status))
        sections.append("[bold]Deployments[/]")
        sections.append(table)
    if report.evals_problem:
        table = _table("JOB", "STATUS", "QUEUED", "TRIGGER")
        for ev in report.evals_problem:
            queued = sum(ev.queued_allocations.values())
            table.add_row(ev.job_id, _status_cell(ev.status), str(queued), ev.triggered_by)
        sections.append("[bold]Evaluations[/]")
        sections.append(table)
    return _panel(Group(*sections), "Activity", border_style="yellow")


class _StepLike(Protocol):
    """Structural type for the progress step object yielded by ``pp.step``."""

    def sub(self, text: str) -> None: ...


app = typer.Typer()


@app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context,
    verbose: Annotated[
        int,
        typer.Option(
            "-v", "--verbose", count=True, help="Increase verbosity (-v debug, -vv trace)."
        ),
    ] = 0,
) -> None:
    """Show an at-a-glance overview of the Nomad cluster."""
    # Accept -v/-vv either before the command (root callback) or here; take the louder.
    verbose = max(getattr(ctx.obj, "verbose", 0), verbose)
    pp.configure(verbosity=verbose)
    report = asyncio.run(_collect(verbose=verbose))
    if verbose:  # separate the progress tree from the dashboard
        pp.console().print()
    render_report(report)


async def _fetch(path: str, coro: Awaitable[Any], *, step: _StepLike | None, verbose: int) -> Any:  # noqa: ANN401
    """Await one resource call, recording it on the progress step per verbosity.

    At ``-v`` the step records the action (the request); at ``-vv`` it also records
    the response (item count and elapsed time).
    """
    start = perf_counter()
    result = await coro
    if step is not None:
        if verbose >= Verbosity.TRACE:
            count = len(result) if isinstance(result, list) else None
            elapsed_ms = (perf_counter() - start) * 1000
            items = f"{count} items, " if count is not None else ""
            step.sub(f"GET /v1{path} → {items}{elapsed_ms:.0f}ms")
        else:
            step.sub(f"GET /v1{path}")
    return result


async def _collect(*, verbose: int) -> StatusReport:
    """Fetch all cluster endpoints concurrently and build a `StatusReport`.

    The default view is silent; ``-v`` shows a `pp.step` tree of the requests we
    make, and ``-vv`` adds each response's item count and elapsed time.
    """
    config = NomadConfig.resolve()
    pp.debug(
        "Resolved Nomad config",
        details=[
            f"address={config.address}",
            f"region={config.region}",
            f"namespace={config.namespace}",
        ],
    )
    async with NomadClient.from_config(config) as client:
        step_cm: contextlib.AbstractContextManager[Any] = (
            pp.step("Querying Nomad cluster") if verbose else contextlib.nullcontext(None)
        )
        with step_cm as step:
            nodes, jobs, allocs, members, leader, deployments, evals = await asyncio.gather(
                _fetch("/nodes", client.nodes.list(), step=step, verbose=verbose),
                _fetch("/jobs", client.jobs.list(), step=step, verbose=verbose),
                _fetch("/allocations", client.allocations.list(), step=step, verbose=verbose),
                _fetch("/agent/members", client.agent.members(), step=step, verbose=verbose),
                _fetch("/status/leader", client.status.leader(), step=step, verbose=verbose),
                _fetch("/deployments", client.deployments.list(), step=step, verbose=verbose),
                _fetch("/evaluations", client.evaluations.list(), step=step, verbose=verbose),
            )
    return build_report(
        nodes=nodes,
        jobs=jobs,
        allocs=allocs,
        config=config,
        members=members,
        leader=leader,
        deployments=deployments,
        evals=evals,
    )
