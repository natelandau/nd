"""Rich rendering for ``nd status``: turn a `StatusReport` into banner and panels."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nclutils import pp
from rich.console import Group
from rich.panel import Panel
from rich.table import Table

from nd.commands.status.report import Health, correlate_nodes
from nd.constants import HOSTS_TWO_COLUMN_MIN_WIDTH
from nd.ui.duration import fmt_uptime
from nd.ui.links import WebUi
from nd.ui.panels import status_table as _table
from nd.ui.panels import titled_panel
from nd.ui.styles import status_cell, status_style

if TYPE_CHECKING:
    from rich.console import RenderableType

    from nd.commands.status.report import HostPanel, NodeRow, StatusReport

_HEALTH_STYLE: dict[Health, str] = {
    Health.HEALTHY: "green",
    Health.DEGRADED: "yellow",
    Health.CRITICAL: "red",
}


def render_report(report: StatusReport) -> None:
    """Print the status report as a banner followed by the cluster panels."""
    console = pp.console()
    console.print(_banner(report))
    console.print(_nodes_panel(report))
    console.print(_jobs_panel(report))
    console.print(_volumes_panel(report))
    if report.deployments_active or report.evals_problem:
        console.print(_activity_panel(report))


def render_hosts(report: StatusReport, host_panels: list[HostPanel]) -> None:
    """Print the host-focused dashboard: banner, one panel per host, then activity.

    The banner is identical to the default view; the per-resource panels are replaced by
    a panel per client node (laid out in two columns on wide terminals), and the Activity
    panel still trails when there is in-progress work.
    """
    console = pp.console()
    console.print(_banner(report))
    if host_panels:
        now_s = time.time()
        web = WebUi(report.ui_url)
        panels = [_host_panel(host, web, now_s) for host in host_panels]
        console.print(_host_grid(panels, console.width))
    else:
        console.print(titled_panel("[dim]No client nodes[/]", "Hosts", expand=True))
    if report.deployments_active or report.evals_problem:
        console.print(_activity_panel(report))


def _host_styles(host: HostPanel) -> tuple[str, str]:
    """Return the (glyph, border) styles for a host, reserving color for problems.

    A healthy host keeps the calm cyan border shared with the other panels and a green
    status dot; a draining/ineligible or unreachable host escalates both to yellow or red.
    """
    if host.status in {"down", "disconnected"}:
        return "red", "red"
    if not host.eligible or host.status != "ready":
        return "yellow", "yellow"
    return "green", "cyan"


def _host_panel(host: HostPanel, web: WebUi, now_s: float) -> Panel:
    """Build one host's panel: a linked title over the jobs running on that host."""
    glyph_style, border_style = _host_styles(host)
    eligibility = "eligible" if host.eligible else "ineligible"
    # Address pairs with the name as the host's identity, and sits early enough that a
    # half-width panel truncates version and eligibility first; those two are recoverable
    # from the dot and border colors, while the address appears nowhere else in this view.
    title = (
        f"[{glyph_style}]●[/] {web.node(host.link_id, host.name)} · [dim]{host.address}[/]"
        f" · {host.status} · {eligibility} · {host.version}"
    )

    if host.jobs:
        body: RenderableType = _table("JOB", "TYPE", "STATUS", "UPTIME")
        for row in host.jobs:
            body.add_row(
                web.job(row.job_id, row.name),
                row.job_type,
                status_cell(row.status),
                fmt_uptime(row.run_start_ns, now_s),
            )
    else:
        body = "[dim]No jobs[/]"

    return titled_panel(body, title, border_style=border_style, expand=True)


def _host_grid(panels: list[Panel], width: int) -> RenderableType:
    """Arrange host panels responsively: two columns when wide, one when narrow.

    A single panel or a terminal narrower than the threshold stacks vertically; otherwise
    the panels fill a two-column grid row-first (an odd final panel leaves an empty cell).
    """
    if width < HOSTS_TWO_COLUMN_MIN_WIDTH or len(panels) < 2:  # noqa: PLR2004
        return Group(*panels)
    grid = Table.grid(padding=(0, 1), expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    for left in range(0, len(panels), 2):
        right: RenderableType = panels[left + 1] if left + 1 < len(panels) else ""
        grid.add_row(panels[left], right)
    return grid


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


def _banner_title(report: StatusReport) -> str:
    """Build the banner panel title from address, region, and namespace."""
    host = report.address.split("://")[-1]
    title = f"Nomad · {host}"
    if report.region:
        title += f" ({report.region})"
    if report.namespace:
        title += f" · {report.namespace}"
    return title


def _fraction(part: int, whole: int, *, suffix: str = "") -> str:
    """Render an ``n/total`` fraction, flagging a shortfall in yellow.

    Values stay at full brightness so the data rail reads louder than the dim label rail.
    """
    value = f"{part}/{whole}"
    colored = value if part >= whole else f"[yellow]{value}[/]"
    return f"{colored} {suffix}" if suffix else colored


def _count(value: int, label: str, *, style: str) -> str:
    """Render a ``value label`` pair, applying ``style`` only when the count is non-zero."""
    shown = f"[{style}]{value}[/]" if value else str(value)
    return f"{shown} {label}"


def _allocs_value(report: StatusReport) -> str:
    """Render the running/failed/pending alloc breakdown with severity-coded counts."""
    return "  ".join(
        (
            _count(report.allocs_running, "running", style="green"),
            _count(report.allocs_failed, "failed", style="red"),
            _count(report.allocs_pending, "pending", style="yellow"),
        )
    )


def _banner(report: StatusReport) -> Panel:
    """Build the top summary banner as an aligned two-column key/value grid."""
    style = _HEALTH_STYLE[report.health]

    # Left group is infrastructure, right group is workload; uppercase labels echo the
    # table column headers below so the banner and panels read as one type system.
    left: list[tuple[str, str]] = [
        ("SERVERS", _fraction(report.servers_alive, report.servers_total, suffix="alive")),
        ("LEADER", report.leader_name or "[red]none[/]"),
        ("NODES", _fraction(report.nodes_ready, report.nodes_total, suffix="ready")),
        ("VOLUMES", str(report.volumes_total)),
    ]
    right: list[tuple[str, str]] = [
        ("JOBS", _fraction(report.jobs_running, report.jobs_total, suffix="running")),
        ("ALLOCS", _allocs_value(report)),
        ("DEPLOYS", _count(len(report.deployments_active), "active", style="cyan")),
        ("EVALS", _count(len(report.evals_problem), "blocked", style="yellow")),
    ]

    # Left-aligned label and value columns form four vertical rails the eye can follow; the
    # dim divider stacks into a continuous hairline that splits infrastructure from workload.
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="left", style="dim")  # left label
    grid.add_column(justify="left")  # left value
    grid.add_column(justify="left", style="dim")  # divider
    grid.add_column(justify="left", style="dim")  # right label
    grid.add_column(justify="left")  # right value
    for (l_label, l_value), (r_label, r_value) in zip(left, right, strict=True):
        grid.add_row(l_label, l_value, "│", r_label, r_value)

    # The verdict lives in the title, right after the host, so the body is pure data.
    verdict = f"[{style}]●[/] [bold {style}]{report.health.value}[/]"
    title = f"{_banner_title(report)}  ·  {verdict}"
    return Panel(grid, title=title, title_align="left", border_style=style, expand=False)


def _nodes_panel(report: StatusReport) -> Panel:
    """Build the combined nodes panel (clients + servers, role-annotated)."""
    rows = correlate_nodes(report.nodes, report.servers)
    if not rows:
        return titled_panel("[dim]No nodes[/]", "Nodes", expand=True)
    web = WebUi(report.ui_url)
    table = _table("NAME", "ADDRESS", "ROLE", "ALLOCS", "STATUS", "ELIGIBLE", "VERSION")
    for row in rows:
        name = web.node(row.link_id, row.name) if row.link_id else row.name
        eligible = (
            "[green]✓[/]" if row.eligible else ("[dim]-[/]" if row.link_id is None else "[red]✗[/]")
        )
        table.add_row(
            name,
            row.address,
            _role_cell(row),
            _allocs_cell(row, report.node_alloc_counts),
            status_cell(row.status),
            eligible,
            row.version,
        )
    return titled_panel(table, "Nodes", expand=True)


def _jobs_panel(report: StatusReport) -> Panel:
    """Build the jobs panel listing every job."""
    if not report.jobs:
        return titled_panel("[dim]No jobs[/]", "Jobs", expand=True)
    now_s = time.time()
    web = WebUi(report.ui_url)
    table = _table("NAME", "TYPE", "STATUS", "UPTIME", "NODES")
    for job in report.jobs:
        nodes = report.job_nodes.get(job.id, [])
        status = report.job_statuses[job.id]
        name = web.job(job.id, job.name)
        # Tint a degraded job's name to match its status cell so the problem row reads as one unit.
        if status == "degraded":
            name = f"[{status_style(status)}]{name}[/]"
        table.add_row(
            name,
            job.type,
            status_cell(status),
            fmt_uptime(job.submit_time, now_s),
            ", ".join(nodes) if nodes else "[dim]-[/]",
        )
    return titled_panel(table, "Jobs", expand=True)


def _volumes_panel(report: StatusReport) -> Panel:
    """Build the host-volumes panel with one row per distinct volume name.

    Node names are shown as plain comma-separated text rather than GUID-linked
    hyperlinks because each row represents a volume (not a node), and embedding
    per-node links here adds visual noise without adding navigation value.
    """
    if not report.volume_rows:
        return titled_panel("[dim]No host volumes[/]", "Volumes", expand=True)
    table = _table("NAME", "NODES", "STATE")
    for row in report.volume_rows:
        nodes_text = ", ".join(row.nodes) if row.nodes else "[dim]-[/]"
        table.add_row(row.name, nodes_text, status_cell(row.state))
    return titled_panel(table, "Volumes", expand=True)


def _activity_panel(report: StatusReport) -> Panel:
    """Build the activity panel (rendered only when there is in-progress work)."""
    sections: list[RenderableType] = []
    if report.deployments_active:
        table = _table("JOB", "VERSION", "STATUS")
        for dep in report.deployments_active:
            table.add_row(dep.job_id, str(dep.job_version), status_cell(dep.status))
        sections.append("[bold]Deployments[/]")
        sections.append(table)
    if report.evals_problem:
        table = _table("JOB", "STATUS", "QUEUED", "TRIGGER")
        for ev in report.evals_problem:
            queued = sum(ev.queued_allocations.values())
            table.add_row(ev.job_id, status_cell(ev.status), str(queued), ev.triggered_by)
        sections.append("[bold]Evaluations[/]")
        sections.append(table)
    return titled_panel(Group(*sections), "Activity", border_style="yellow", expand=True)
