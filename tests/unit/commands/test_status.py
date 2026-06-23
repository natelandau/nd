"""Tests for the status command."""

import asyncio

import respx
from nclutils import pp
from rich.console import Console
from typer.testing import CliRunner

from nd.commands.status import Health, build_report
from nd.nomad.config import NomadConfig
from nd.nomad.models.agent import AgentMember
from nd.nomad.models.allocation import AllocListStub
from nd.nomad.models.deployment import DeploymentListStub
from nd.nomad.models.evaluation import EvalListStub
from nd.nomad.models.job import JobListStub
from nd.nomad.models.node import NodeListStub

_CONFIG = NomadConfig(address="http://nomad.test:4646", region="global", namespace="default")


def _member(*, name="mf1.global", addr="10.0.0.1", status="alive", build="2.0.3") -> AgentMember:
    return AgentMember(name=name, addr=addr, status=status, tags={"build": build, "port": "4647"})


def _deployment(*, job_id="web", status="running", job_version=3) -> DeploymentListStub:
    return DeploymentListStub(
        id=f"dep-{job_id}",
        job_id=job_id,
        namespace="default",
        status=status,
        job_version=job_version,
        create_index=1,
        modify_index=2,
    )


def _eval(*, job_id="web", status="complete", queued=None) -> EvalListStub:
    return EvalListStub(
        id=f"eval-{job_id}",
        job_id=job_id,
        namespace="default",
        status=status,
        type="service",
        triggered_by="job-register",
        queued_allocations=queued or {},
        create_index=1,
        modify_index=2,
    )


def _node(
    *, name="srv1", status="ready", drain=False, eligibility="eligible", address="10.0.0.1"
) -> NodeListStub:
    return NodeListStub(
        id=name,
        datacenter="dc1",
        name=name,
        node_class="",
        node_pool="default",
        address=address,
        drain=drain,
        scheduling_eligibility=eligibility,
        status=status,
        version="1.9.0",
        create_index=1,
        modify_index=2,
    )


def _job(*, name="web", status="running", submit_time=0) -> JobListStub:
    return JobListStub(
        id=name,
        name=name,
        type="service",
        status=status,
        priority=50,
        namespace="default",
        submit_time=submit_time,
        create_index=1,
        modify_index=2,
    )


def _alloc(
    *, name="web.alloc", client_status="running", node_id="srv1", job_id="web"
) -> AllocListStub:
    return AllocListStub(
        id=name,
        name=name,
        namespace="default",
        node_id=node_id,
        job_id=job_id,
        task_group="web",
        client_status=client_status,
        desired_status="run",
        create_index=1,
        modify_index=2,
    )


def test_build_report_all_healthy():
    """Verify a clean cluster reports HEALTHY and retains full counts."""
    # Given all-ready nodes, running jobs, and running allocations
    nodes = [_node(name="srv1"), _node(name="srv2")]
    jobs = [_job(name="web"), _job(name="api")]
    allocs = [_alloc(name="a1"), _alloc(name="a2", client_status="complete")]

    # When building the report
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # Then it is healthy with full counts and lists
    assert report.health is Health.HEALTHY
    assert report.nodes_ready == 2
    assert report.nodes_total == 2
    assert report.jobs_total == 2
    assert report.jobs_running == 2
    assert report.allocs_total == 2
    assert report.allocs_running == 1


def test_build_report_counts_active_allocs_per_node():
    """Verify per-node alloc counts include running/pending but exclude terminal allocs."""
    # Given two nodes and a mix of active and terminal allocations across them
    nodes = [_node(name="srv1"), _node(name="srv2")]
    allocs = [
        _alloc(name="a1", node_id="srv1", client_status="running"),
        _alloc(name="a2", node_id="srv1", client_status="pending"),
        _alloc(name="a3", node_id="srv1", client_status="complete"),
        _alloc(name="a4", node_id="srv2", client_status="running"),
    ]

    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=allocs, config=_CONFIG)

    # Then only active (running + pending) allocs are counted, keyed by node id
    assert report.node_alloc_counts == {"srv1": 2, "srv2": 1}


def test_build_report_maps_jobs_to_node_names():
    """Verify each job maps to the sorted, de-duplicated names of its active alloc nodes."""
    # Given nodes whose ids differ from their display names and active allocs spread across them
    nodes = [
        NodeListStub(
            id="id-z",
            datacenter="dc1",
            name="zeta",
            node_class="",
            node_pool="default",
            address="10.0.0.1",
            drain=False,
            scheduling_eligibility="eligible",
            status="ready",
            version="1.9.0",
            create_index=1,
            modify_index=2,
        ),
        NodeListStub(
            id="id-a",
            datacenter="dc1",
            name="alpha",
            node_class="",
            node_pool="default",
            address="10.0.0.2",
            drain=False,
            scheduling_eligibility="eligible",
            status="ready",
            version="1.9.0",
            create_index=1,
            modify_index=2,
        ),
    ]
    allocs = [
        _alloc(name="w1", job_id="web", node_id="id-z", client_status="running"),
        _alloc(name="w2", job_id="web", node_id="id-a", client_status="running"),
        _alloc(name="w3", job_id="web", node_id="id-z", client_status="running"),
        _alloc(name="w4", job_id="web", node_id="id-a", client_status="complete"),
        _alloc(name="a1", job_id="api", node_id="id-a", client_status="pending"),
    ]

    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=allocs, config=_CONFIG)

    # Then job nodes are resolved to names, de-duplicated and sorted; terminal allocs excluded
    assert report.job_nodes == {"web": ["alpha", "zeta"], "api": ["alpha"]}


def test_render_report_nodes_panel_shows_alloc_count():
    """Verify the nodes panel renders an ALLOCS column with each node's active count."""
    # Given a node carrying three active allocations
    nodes = [_node(name="srv1")]
    allocs = [
        _alloc(name="a1", node_id="srv1", client_status="running"),
        _alloc(name="a2", node_id="srv1", client_status="running"),
        _alloc(name="a3", node_id="srv1", client_status="pending"),
    ]
    report = build_report(nodes=nodes, jobs=[], allocs=allocs, config=_CONFIG)

    # When rendering it
    text = _render_to_text(report)

    # Then the ALLOCS column header and the node's count appear
    assert "ALLOCS" in text
    assert "3" in text


def test_render_report_jobs_panel_shows_nodes_column():
    """Verify the jobs panel renders a NODES column listing comma-separated node names."""
    # Given a job whose allocations are deployed on two nodes
    nodes = [_node(name="srv1"), _node(name="srv2")]
    jobs = [_job(name="web")]
    allocs = [
        _alloc(name="a1", job_id="web", node_id="srv1"),
        _alloc(name="a2", job_id="web", node_id="srv2"),
    ]
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # When rendering it
    text = _render_to_text(report)

    # Then the NODES column header and the comma-separated node names appear
    assert "NODES" in text
    assert "srv1, srv2" in text


def test_build_report_ui_url_defaults_to_address():
    """Verify the report's UI base URL falls back to the API address."""
    # Given a config without an explicit ui_url
    config = NomadConfig(address="http://nomad.test:4646/")

    # When building the report
    report = build_report(nodes=[], jobs=[], allocs=[], config=config)

    # Then ui_url is the address with any trailing slash trimmed
    assert report.ui_url == "http://nomad.test:4646"


def test_build_report_ui_url_uses_config_override():
    """Verify a configured ui_url overrides the API address for links."""
    # Given a config with an explicit ui_url
    config = NomadConfig(address="http://10.0.0.1:4646", ui_url="https://nomad.example.org/")

    # When building the report
    report = build_report(nodes=[], jobs=[], allocs=[], config=config)

    # Then the configured ui_url wins (trailing slash trimmed)
    assert report.ui_url == "https://nomad.example.org"


def test_build_report_sorts_everything_alphabetically():
    """Verify nodes, jobs, and servers are sorted by name."""
    # Given unsorted nodes, jobs, and servers
    nodes = [_node(name="zeta"), _node(name="alpha"), _node(name="mid")]
    jobs = [_job(name="web"), _job(name="api"), _job(name="db")]
    members = [
        _member(name="zeta.global"),
        _member(name="alpha.global"),
        _member(name="mid.global"),
    ]

    # When building the report
    report = build_report(nodes=nodes, jobs=jobs, allocs=[], config=_CONFIG, members=members)

    # Then each list is alphabetical by name
    assert [n.name for n in report.nodes] == ["alpha", "mid", "zeta"]
    assert [j.name for j in report.jobs] == ["api", "db", "web"]
    assert [s.name for s in report.servers] == ["alpha", "mid", "zeta"]


def test_build_report_resolves_servers_and_leader():
    """Verify server members are summarized and the leader is identified by address."""
    # Given three alive servers and a leader address pointing at one of them
    members = [
        _member(name="mf1.global", addr="10.0.0.1"),
        _member(name="rpi1.global", addr="10.0.0.2"),
        _member(name="rpi2.global", addr="10.0.0.3"),
    ]

    # When building the report with the leader's RPC address
    report = build_report(
        nodes=[], jobs=[], allocs=[], config=_CONFIG, members=members, leader="10.0.0.2:4647"
    )

    # Then the servers are counted and the leader is named (region suffix stripped)
    assert report.servers_total == 3
    assert report.servers_alive == 3
    assert report.leader_name == "rpi1"
    assert report.health is Health.HEALTHY


def test_build_report_matches_leader_by_rpc_tag_when_serf_addr_differs():
    """Verify the leader is matched via rpc_addr/port tags, not the serf address."""
    # Given a server whose serf addr differs from its RPC advertise address
    member = AgentMember(
        name="mf1.global",
        addr="10.0.50.1",
        status="alive",
        tags={"build": "2.0.3", "rpc_addr": "10.0.0.1", "port": "4647"},
    )

    # When the leader endpoint reports the RPC address
    report = build_report(
        nodes=[], jobs=[], allocs=[], config=_CONFIG, members=[member], leader="10.0.0.1:4647"
    )

    # Then the leader is identified and the cluster is healthy (not a false CRITICAL)
    assert report.leader_name == "mf1"
    assert report.health is Health.HEALTHY


def test_build_report_degraded_on_lost_alloc():
    """Verify an allocation outside running/complete (e.g. lost) degrades health."""
    # Given a lost allocation
    report = build_report(
        nodes=[], jobs=[], allocs=[_alloc(name="a1", client_status="lost")], config=_CONFIG
    )

    # Then the cluster is degraded even though it is neither failed nor pending
    assert report.health is Health.DEGRADED


def test_build_report_critical_when_no_leader():
    """Verify servers present without an elected leader is CRITICAL."""
    # Given servers but no leader address
    members = [_member(name="mf1.global", addr="10.0.0.1")]

    # When building the report with an empty leader
    report = build_report(nodes=[], jobs=[], allocs=[], config=_CONFIG, members=members, leader="")

    # Then the cluster is critical
    assert report.leader_name is None
    assert report.health is Health.CRITICAL


def test_build_report_degraded_when_server_not_alive():
    """Verify a non-alive server degrades the cluster."""
    # Given a failed follower alongside the alive leader
    members = [
        _member(name="mf1.global", addr="10.0.0.1"),
        _member(name="rpi1.global", addr="10.0.0.2", status="failed"),
    ]

    # When building the report
    report = build_report(
        nodes=[], jobs=[], allocs=[], config=_CONFIG, members=members, leader="10.0.0.1:4647"
    )

    # Then the cluster is degraded
    assert report.servers_alive == 1
    assert report.health is Health.DEGRADED


def test_build_report_flags_active_deployments_and_problem_evals():
    """Verify running deployments and blocked/queued evals are surfaced."""
    # Given a healthy single-server cluster with an active deploy and a blocked eval
    members = [_member(addr="10.0.0.1")]
    deployments = [
        _deployment(job_id="web", status="running"),
        _deployment(job_id="db", status="successful"),
    ]
    evals = [
        _eval(job_id="web", status="blocked"),
        _eval(job_id="api", status="pending", queued={"group": 2}),
        _eval(job_id="stale", status="complete", queued={"group": 5}),
        _eval(job_id="db", status="complete"),
    ]

    # When building the report
    report = build_report(
        nodes=[],
        jobs=[],
        allocs=[],
        config=_CONFIG,
        members=members,
        leader="10.0.0.1:4647",
        deployments=deployments,
        evals=evals,
    )

    # Then only the active deploy and live problem evals are kept (terminal "stale" excluded)
    assert [d.job_id for d in report.deployments_active] == ["web"]
    assert [e.job_id for e in report.evals_problem] == ["api", "web"]
    assert report.health is Health.DEGRADED


def test_build_report_critical_when_node_down():
    """Verify a down node makes the cluster CRITICAL."""
    # Given one down node
    nodes = [_node(name="srv1"), _node(name="srv2", status="down")]

    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG)

    # Then the verdict is critical
    assert report.health is Health.CRITICAL


def test_build_report_degraded_on_draining_node():
    """Verify a draining node degrades an otherwise healthy cluster."""
    # Given a draining, ineligible node
    nodes = [_node(name="srv1", drain=True, eligibility="ineligible")]

    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG)

    # Then the verdict is degraded
    assert report.health is Health.DEGRADED


def test_build_report_degraded_on_dead_job():
    """Verify a non-running job degrades the cluster while all jobs stay listed."""
    # Given a mix of running and dead jobs
    jobs = [_job(name="web"), _job(name="batch", status="dead")]

    # When building the report
    report = build_report(nodes=[], jobs=jobs, allocs=[], config=_CONFIG)

    # Then every job is listed and the verdict is degraded
    assert [j.name for j in report.jobs] == ["batch", "web"]
    assert report.jobs_total == 2
    assert report.jobs_running == 1
    assert report.health is Health.DEGRADED


def test_build_report_degraded_on_failed_alloc():
    """Verify a failed allocation degrades the cluster and is counted."""
    # Given running, complete, and failed allocations
    allocs = [
        _alloc(name="a1"),
        _alloc(name="a2", client_status="complete"),
        _alloc(name="a3", client_status="failed"),
    ]

    # When building the report
    report = build_report(nodes=[], jobs=[], allocs=allocs, config=_CONFIG)

    # Then failure counts are tracked and the cluster is degraded
    assert report.allocs_total == 3
    assert report.allocs_failed == 1
    assert report.allocs_running == 1
    assert report.health is Health.DEGRADED


def _render_to_text(report) -> str:
    """Render a report through a recording emitter and return the captured text."""
    capture = Console(theme=pp.THEME, record=True, force_terminal=True, width=100)
    emitter = pp.Emitter(console=capture, err_console=capture)
    original = pp.get_default()
    pp.set_default(emitter)
    try:
        from nd.commands.status import render_report

        render_report(report)
    finally:
        pp.set_default(original)
    return capture.export_text()


def test_render_report_shows_health_nodes_and_addresses():
    """Verify a healthy report prints the verdict, node names, and node addresses."""
    # Given a healthy report with two ready nodes carrying addresses
    nodes = [_node(name="srv1", address="10.0.0.11"), _node(name="srv2", address="10.0.0.12")]
    jobs = [_job(name="web")]
    allocs = [_alloc(name="a1")]
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # When rendering it
    text = _render_to_text(report)

    # Then the verdict, node names, and node addresses appear
    assert "HEALTHY" in text
    assert "srv1" in text
    assert "10.0.0.11" in text


def test_render_report_banner_includes_deployment_and_eval_metrics():
    """Verify the banner surfaces deployment and evaluation counts."""
    # Given a clean cluster (no activity panel will render)
    report = build_report(
        nodes=[_node()],
        jobs=[_job()],
        allocs=[],
        config=_CONFIG,
        members=[_member(addr="10.0.0.1")],
        leader="10.0.0.1:4647",
    )

    # When rendering it
    text = _render_to_text(report)

    # Then the banner carries the deployment and eval metrics
    assert "Deployments 0 active" in text
    assert "Evals 0 blocked" in text


def test_render_report_lists_all_jobs():
    """Verify every job is rendered, healthy or not."""
    # Given both running and dead jobs
    jobs = [_job(name="web"), _job(name="batch", status="dead")]
    report = build_report(nodes=[_node()], jobs=jobs, allocs=[], config=_CONFIG)

    # When rendering it
    text = _render_to_text(report)

    # Then the degraded verdict and all rows appear (running ones are not hidden)
    assert "DEGRADED" in text
    assert "batch" in text
    assert "web" in text
    assert "hidden" not in text


def test_render_report_combines_servers_into_nodes_table():
    """Verify servers are folded into the Nodes table with role annotations."""
    # Given a leader+client host, a follower host, and a client-only host
    nodes = [
        _node(name="mf1", address="10.0.0.1"),
        _node(name="rpi1", address="10.0.0.2"),
        _node(name="box", address="10.0.0.9"),
    ]
    members = [
        _member(name="mf1.global", addr="10.0.0.1"),
        _member(name="rpi1.global", addr="10.0.0.2"),
    ]
    report = build_report(
        nodes=nodes, jobs=[], allocs=[], config=_CONFIG, members=members, leader="10.0.0.1:4647"
    )

    # When rendering it
    text = _render_to_text(report)

    # Then roles appear in the Nodes table for the merged hosts
    assert "leader" in text
    assert "server" in text
    assert "client" in text
    assert "box" in text


def test_correlate_nodes_annotates_roles_and_appends_server_only():
    """Verify nodes get server roles by address and server-only hosts are appended."""
    # Given a leader host, a client-only host, and a server with no client node
    from nd.commands.status import ServerInfo, correlate_nodes

    nodes = [_node(name="mf1", address="10.0.0.1"), _node(name="box", address="10.0.0.9")]
    servers = [
        ServerInfo(name="mf1", addr="10.0.0.1", status="alive", version="2.0.3", is_leader=True),
        ServerInfo(name="ghost", addr="10.0.0.5", status="alive", version="2.0.3", is_leader=False),
    ]

    # When correlating
    rows = correlate_nodes(nodes, servers)

    # Then roles are assigned and the server-only host appears with no client link
    by_name = {r.name: r for r in rows}
    assert by_name["mf1"].role == "leader"
    assert by_name["box"].role == "client"
    assert by_name["ghost"].role == "server"
    assert by_name["ghost"].link_id is None


def test_correlate_nodes_matches_by_name_when_addresses_differ():
    """Verify a server folds into its client node by host name when addresses differ."""
    # Given a node and its server whose serf addr differs from the node HTTP address
    from nd.commands.status import ServerInfo, correlate_nodes

    nodes = [_node(name="mf1", address="10.0.30.95")]
    servers = [
        ServerInfo(name="mf1", addr="10.0.0.1", status="alive", version="2.0.3", is_leader=True)
    ]

    # When correlating
    rows = correlate_nodes(nodes, servers)

    # Then they merge into a single leader-annotated client row (no duplicate server row)
    assert len(rows) == 1
    assert rows[0].role == "leader"
    assert rows[0].link_id == "mf1"


def test_fmt_uptime_renders_compact_durations():
    """Verify uptime formats nanosecond submit times into compact durations."""
    # Given a fixed reference time
    from nd.ui.duration import fmt_uptime

    now_s = 1_000_000.0

    # When formatting various submit ages (now minus N seconds, in nanoseconds)
    # Then durations are compact and zero/unknown render as a dash
    assert fmt_uptime(int((now_s - 90_000) * 1_000_000_000), now_s) == "1d 1h"
    assert fmt_uptime(int((now_s - 3700) * 1_000_000_000), now_s) == "1h 1m"
    assert fmt_uptime(int((now_s - 45) * 1_000_000_000), now_s) == "45s"
    assert fmt_uptime(0, now_s) == "-"


def test_render_report_omits_activity_panel_when_clean():
    """Verify the activity panel is absent when there is no in-progress work."""
    # Given a clean cluster with no active deploys or problem evals
    report = build_report(
        nodes=[_node()],
        jobs=[_job()],
        allocs=[],
        config=_CONFIG,
        members=[_member(addr="10.0.0.1")],
        leader="10.0.0.1:4647",
    )

    # When rendering it
    text = _render_to_text(report)

    # Then no activity panel is shown
    assert "Activity" not in text


def test_render_report_shows_activity_panel_when_present():
    """Verify the activity panel renders active deployments and problem evals."""
    # Given an active deployment and a blocked evaluation
    report = build_report(
        nodes=[],
        jobs=[],
        allocs=[],
        config=_CONFIG,
        members=[_member(addr="10.0.0.1")],
        leader="10.0.0.1:4647",
        deployments=[_deployment(job_id="web", status="running")],
        evals=[_eval(job_id="api", status="blocked")],
    )

    # When rendering it
    text = _render_to_text(report)

    # Then the activity panel and its rows appear
    assert "Activity" in text
    assert "Deployments" in text
    assert "Evaluations" in text
    assert "web" in text
    assert "api" in text


def test_render_report_links_names_to_webui():
    """Verify node and job names are rendered as links to the web UI."""
    # Given a report with one node and one job
    nodes = [_node(name="srv1")]
    jobs = [_job(name="web")]
    report = build_report(nodes=nodes, jobs=jobs, allocs=[], config=_CONFIG)

    capture = Console(theme=pp.THEME, record=True, force_terminal=True, width=120)
    emitter = pp.Emitter(console=capture, err_console=capture)
    original = pp.get_default()
    pp.set_default(emitter)
    try:
        from nd.commands.status import render_report

        render_report(report)
    finally:
        pp.set_default(original)
    html = capture.export_html()

    # Then the exported output carries hyperlinks to the clients and jobs routes
    assert "http://nomad.test:4646/ui/clients/srv1" in html
    assert "http://nomad.test:4646/ui/jobs/web" in html


_ADDR = "http://nomad.test:4646"
_MEMBERS_JSON = {
    "Members": [
        {
            "Name": "srv1.global",
            "Addr": "10.0.0.1",
            "Status": "alive",
            "Tags": {"build": "1.9.0", "port": "4647"},
        }
    ]
}
_NODE_JSON = {
    "ID": "srv1",
    "Datacenter": "dc1",
    "Name": "srv1",
    "NodeClass": "",
    "NodePool": "default",
    "Drain": False,
    "SchedulingEligibility": "eligible",
    "Status": "ready",
    "Version": "1.9.0",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}
_JOB_JSON = {
    "ID": "web",
    "Name": "web",
    "Type": "service",
    "Status": "running",
    "Priority": 50,
    "Namespace": "default",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}
_ALLOC_JSON = {
    "ID": "a1",
    "Name": "web.alloc",
    "Namespace": "default",
    "NodeID": "srv1",
    "JobID": "web",
    "TaskGroup": "web",
    "ClientStatus": "running",
    "DesiredStatus": "run",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}


def _mock_all(router: respx.Router) -> None:
    router.get(f"{_ADDR}/v1/nodes").respond(json=[_NODE_JSON])
    router.get(f"{_ADDR}/v1/jobs").respond(json=[_JOB_JSON])
    router.get(f"{_ADDR}/v1/allocations").respond(json=[_ALLOC_JSON])
    router.get(f"{_ADDR}/v1/agent/members").respond(json=_MEMBERS_JSON)
    router.get(f"{_ADDR}/v1/status/leader").respond(json="10.0.0.1:4647")
    router.get(f"{_ADDR}/v1/deployments").respond(json=[])
    router.get(f"{_ADDR}/v1/evaluations").respond(json=[])


def test_collect_aggregates_all_endpoints(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify _collect fetches every endpoint and returns a populated report."""
    # Given a fully mocked cluster and an isolated config environment
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _mock_all(httpx2_mock)

    # When collecting status
    from nd.commands.status import _collect

    report = asyncio.run(_collect(verbose=0))

    # Then the report reflects the mocked data
    assert report.health is Health.HEALTHY
    assert report.nodes_total == 1
    assert report.jobs_running == 1
    assert report.allocs_running == 1
    assert report.servers_total == 1
    assert report.leader_name == "srv1"


def test_status_command_exits_zero(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify the status command runs end to end and exits successfully."""
    # Given a fully mocked cluster and an isolated config environment
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _mock_all(httpx2_mock)

    # When invoking the status sub-app
    from nd.commands import status

    result = CliRunner().invoke(status.app, [])

    # Then it exits cleanly
    assert result.exit_code == 0


def test_verbose_flag_works_before_or_after_command(
    httpx2_mock: respx.Router, monkeypatch, tmp_path
):
    """Verify -v is accepted both as `nd -v status` and `nd status -v`."""
    # Given a fully mocked cluster and an isolated config environment
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _mock_all(httpx2_mock)

    # When invoking the root app with -v before and after the command name
    from nd import cli

    runner = CliRunner()

    # Then both positions are accepted and exit cleanly
    assert runner.invoke(cli.app, ["-v", "status"]).exit_code == 0
    assert runner.invoke(cli.app, ["status", "-v"]).exit_code == 0
