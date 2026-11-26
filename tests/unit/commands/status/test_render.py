"""Tests for status report rendering."""

import pytest

from nd.commands.status.render import render_hosts, render_report
from nd.commands.status.report import build_host_report, build_report
from nd.nomad.config import NomadConfig
from tests.builders import (
    agent_member,
    alloc_stub,
    deployment,
    eval_stub,
    host_volume_stub,
    job_stub,
    node_stub,
)
from tests.helpers import NOMAD_TEST_ADDR, capture_output

_CONFIG = NomadConfig(address=NOMAD_TEST_ADDR, region="global", namespace="default")


def test_render_report_shows_health_nodes_and_addresses() -> None:
    """Verify a healthy report prints the verdict, node names, and node addresses."""
    # Given a healthy report with two ready nodes carrying addresses
    nodes = [node_stub("srv1", address="10.0.0.11"), node_stub("srv2", address="10.0.0.12")]
    report = build_report(nodes=nodes, jobs=[job_stub()], allocs=[alloc_stub()], config=_CONFIG)
    console = capture_output()

    # When rendering it
    render_report(report)

    # Then the verdict, node names, and node addresses appear
    text = console.export_text()
    assert "HEALTHY" in text
    assert "srv1" in text
    assert "10.0.0.11" in text


def test_render_report_jobs_panel_shows_degraded_for_unreplaced_failure() -> None:
    """Verify the jobs panel renders a degraded row when a job's latest alloc failed unreplaced."""
    # Given a running job with a failed head allocation Nomad has not replaced
    nodes = [node_stub("srv1"), node_stub("srv2")]
    allocs = [
        alloc_stub("d1", job_id="diun", node_id="srv1", client_status="running"),
        alloc_stub("d2", job_id="diun", node_id="srv2", client_status="failed"),
    ]
    report = build_report(nodes=nodes, jobs=[job_stub("diun")], allocs=allocs, config=_CONFIG)
    console = capture_output()

    # When rendering it
    render_report(report)

    # Then the diun row shows degraded rather than running
    assert "degraded" in console.export_text()


def test_render_report_nodes_panel_shows_alloc_count() -> None:
    """Verify the nodes panel renders an ALLOCS column with each node's active count."""
    # Given a node carrying three active allocations
    allocs = [
        alloc_stub("a1", node_id="srv1", client_status="running"),
        alloc_stub("a2", node_id="srv1", client_status="running"),
        alloc_stub("a3", node_id="srv1", client_status="pending"),
    ]
    report = build_report(nodes=[node_stub("srv1")], jobs=[], allocs=allocs, config=_CONFIG)
    console = capture_output()

    # When rendering it
    render_report(report)

    # Then the ALLOCS column header and the node's count appear
    text = console.export_text()
    assert "ALLOCS" in text
    assert "3" in text


def test_render_report_jobs_panel_shows_nodes_column() -> None:
    """Verify the jobs panel renders a NODES column listing comma-separated node names."""
    # Given a job whose allocations are deployed on two nodes
    nodes = [node_stub("srv1"), node_stub("srv2")]
    allocs = [alloc_stub("a1", node_id="srv1"), alloc_stub("a2", node_id="srv2")]
    report = build_report(nodes=nodes, jobs=[job_stub("web")], allocs=allocs, config=_CONFIG)
    console = capture_output()

    # When rendering it
    render_report(report)

    # Then the NODES column header and the comma-separated node names appear
    text = console.export_text()
    assert "NODES" in text
    assert "srv1, srv2" in text


def test_render_report_clean_cluster_shows_metrics_without_activity_panel() -> None:
    """Verify a clean cluster's banner shows zero deploy and eval counts and no activity panel."""
    # Given a clean cluster with no active deploys or problem evals
    report = build_report(
        nodes=[node_stub()],
        jobs=[job_stub()],
        allocs=[],
        config=_CONFIG,
        members=[agent_member(addr="10.0.0.1")],
        leader="10.0.0.1:4647",
    )
    console = capture_output()

    # When rendering it
    render_report(report)

    # Then the banner carries the deployment and eval metrics
    text = console.export_text()
    assert "DEPLOYS" in text
    assert "0 active" in text
    assert "EVALS" in text
    assert "0 blocked" in text
    # And no activity panel is shown
    assert "Activity" not in text


def test_render_report_lists_all_jobs() -> None:
    """Verify every job is rendered, healthy or not."""
    # Given both running and dead jobs
    jobs = [job_stub("web"), job_stub("batch", status="dead")]
    report = build_report(nodes=[node_stub()], jobs=jobs, allocs=[], config=_CONFIG)
    console = capture_output()

    # When rendering it
    render_report(report)

    # Then the degraded verdict and all rows appear (running ones are not hidden)
    text = console.export_text()
    assert "DEGRADED" in text
    assert "batch" in text
    assert "web" in text
    assert "hidden" not in text


def test_render_report_combines_servers_into_nodes_table() -> None:
    """Verify servers are folded into the Nodes table with role annotations."""
    # Given a leader+client host, a follower host, and a client-only host
    nodes = [
        node_stub("mf1", address="10.0.0.1"),
        node_stub("rpi1", address="10.0.0.2"),
        node_stub("box", address="10.0.0.9"),
    ]
    members = [
        agent_member("mf1.global", addr="10.0.0.1"),
        agent_member("rpi1.global", addr="10.0.0.2"),
    ]
    report = build_report(
        nodes=nodes, jobs=[], allocs=[], config=_CONFIG, members=members, leader="10.0.0.1:4647"
    )
    console = capture_output()

    # When rendering it
    render_report(report)

    # Then roles appear in the Nodes table for the merged hosts
    text = console.export_text()
    assert "leader" in text
    assert "server" in text
    assert "client" in text
    assert "box" in text


def test_render_report_shows_activity_panel_when_present() -> None:
    """Verify the activity panel renders active deployments and problem evals."""
    # Given an active deployment and a blocked evaluation
    report = build_report(
        nodes=[],
        jobs=[],
        allocs=[],
        config=_CONFIG,
        members=[agent_member(addr="10.0.0.1")],
        leader="10.0.0.1:4647",
        deployments=[deployment("web", status="running")],
        evals=[eval_stub("api", status="blocked")],
    )
    console = capture_output()

    # When rendering it
    render_report(report)

    # Then the activity panel and its rows appear
    text = console.export_text()
    assert "Activity" in text
    assert "Deployments" in text
    assert "Evaluations" in text
    assert "web" in text
    assert "api" in text


def test_render_report_links_names_to_webui() -> None:
    """Verify node and job names are rendered as links to the web UI."""
    # Given a report with one node and one job
    report = build_report(
        nodes=[node_stub("srv1")], jobs=[job_stub("web")], allocs=[], config=_CONFIG
    )
    console = capture_output(width=120)

    # When rendering it
    render_report(report)

    # Then the exported output carries hyperlinks to the clients and jobs routes
    html = console.export_html()
    assert f"{NOMAD_TEST_ADDR}/ui/clients/srv1" in html
    assert f"{NOMAD_TEST_ADDR}/ui/jobs/web" in html


def test_render_report_shows_volumes_panel() -> None:
    """Verify the dashboard renders a Volumes panel listing volumes with node names."""
    # Given a report with one volume registered on two nodes
    vols = [host_volume_stub("data", node_id="n1"), host_volume_stub("data", node_id="n2")]
    nodes = [node_stub("n1"), node_stub("n2")]
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG, volumes=vols)
    console = capture_output()

    # When rendering it
    render_report(report)

    # Then the volume name and both node names appear under a Volumes heading
    text = console.export_text()
    assert "Volumes" in text
    assert "data" in text
    assert "n1" in text
    assert "n2" in text


def test_render_hosts_shows_banner_and_per_host_jobs() -> None:
    """Verify the host view keeps the banner and renders each host's jobs (no volumes)."""
    # Given two nodes on distinct addresses and a job placed on one
    nodes = [node_stub("alpha", address="10.0.0.11"), node_stub("beta", address="10.0.0.12")]
    jobs = [job_stub("web")]
    allocs = [alloc_stub("w1", node_id="alpha", task_group="frontend", create_time=1_000_000_000)]
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)
    panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs, servers=[])
    console = capture_output()

    # When rendering the host view
    render_hosts(report=report, host_panels=panels)

    # Then the banner verdict, both host names and addresses, and the job row's columns appear
    text = console.export_text()
    assert "HEALTHY" in text
    assert "alpha" in text
    assert "beta" in text
    assert "10.0.0.11" in text
    assert "10.0.0.12" in text
    assert "TYPE" in text
    assert "UPTIME" in text
    assert "web" in text
    # And the host view carries neither a Volumes sub-table nor a GROUP column
    assert "Volumes" not in text
    assert "GROUP" not in text


def test_render_hosts_shows_placeholder_for_empty_host() -> None:
    """Verify a host with no allocs still renders with a jobs placeholder."""
    # Given a node with nothing placed on it
    nodes = [node_stub("alpha")]
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG)
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[], servers=[])
    console = capture_output()

    # When rendering the host view
    render_hosts(report=report, host_panels=panels)

    # Then the panel still appears with an empty-state placeholder and no volumes section
    text = console.export_text()
    assert "alpha" in text
    assert "No jobs" in text
    assert "No volumes" not in text


def test_render_hosts_shows_server_only_host() -> None:
    """Verify a server with no client agent renders as its own host panel."""
    # Given a client node and a server member with no client agent
    nodes = [node_stub("alpha")]
    members = [agent_member("ctl", addr="10.0.0.5")]
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG, members=members)
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[], servers=report.servers)
    console = capture_output()

    # When rendering the host view
    render_hosts(report=report, host_panels=panels)

    # Then both machines render, the server-only one with its address
    text = console.export_text()
    assert "alpha" in text
    assert "ctl" in text
    assert "10.0.0.5" in text


def test_render_hosts_shows_activity_panel_when_present() -> None:
    """Verify the host view still renders the Activity panel for in-progress work."""
    # Given an active deployment and a blocked evaluation
    nodes = [node_stub("alpha")]
    report = build_report(
        nodes=nodes,
        jobs=[],
        allocs=[],
        config=_CONFIG,
        deployments=[deployment("web", status="running")],
        evals=[eval_stub("api", status="blocked")],
    )
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[], servers=[])
    console = capture_output()

    # When rendering the host view
    render_hosts(report=report, host_panels=panels)

    # Then the activity panel and its sections appear
    text = console.export_text()
    assert "Activity" in text
    assert "Deployments" in text


@pytest.mark.parametrize(
    ("width", "side_by_side"),
    [pytest.param(160, True, id="wide"), pytest.param(90, False, id="narrow")],
)
def test_render_hosts_lays_out_panels_by_width(width: int, *, side_by_side: bool) -> None:
    """Verify a wide terminal puts two host panels in one row and a narrow one stacks them."""
    # Given two nodes
    nodes = [node_stub("alpha"), node_stub("beta")]
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG)
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[], servers=[])
    console = capture_output(width=width)

    # When rendering at a width above or below the two-column threshold
    render_hosts(report=report, host_panels=panels)

    # Then both panels render, and their titles share a line only when wide
    text = console.export_text()
    assert "alpha" in text
    assert "beta" in text
    assert any("alpha" in line and "beta" in line for line in text.splitlines()) is side_by_side
