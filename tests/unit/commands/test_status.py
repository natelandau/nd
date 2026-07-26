"""Tests for the status command."""

import asyncio

import respx
from nclutils import pp
from rich.console import Console
from typer.testing import CliRunner

from nd.commands.status import Health, StatusReport, build_report
from nd.commands.status.report import (
    _alloc_run_start_ns,
    _rfc3339_to_ns,
    build_host_report,
)
from nd.nomad.config import NomadConfig
from nd.nomad.models.agent import AgentMember
from nd.nomad.models.allocation import AllocListStub, TaskState
from nd.nomad.models.deployment import DeploymentListStub
from nd.nomad.models.evaluation import EvalListStub
from nd.nomad.models.job import JobListStub
from nd.nomad.models.node import NodeListStub
from nd.nomad.models.volume import HostVolumeListStub

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
    *,
    name="web.alloc",
    client_status="running",
    desired_status="run",
    node_id="srv1",
    job_id="web",
    task_group="web",
    next_allocation="",
    create_time=0,
    task_states=None,
) -> AllocListStub:
    return AllocListStub(
        id=name,
        name=name,
        namespace="default",
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


def _task_state(*, state="running", started_at="") -> TaskState:
    return TaskState(state=state, failed=False, restarts=0, started_at_raw=started_at)


def test_rfc3339_to_ns_parses_whole_and_fractional_seconds():
    """Verify _rfc3339_to_ns converts RFC3339 timestamps to precise unix nanoseconds."""
    # Given RFC3339 timestamps relative to the unix epoch
    # When parsing whole and fractional seconds (with a trailing Z)
    # Then the nanosecond value is exact, with sub-microsecond digits truncated
    assert _rfc3339_to_ns("1970-01-01T00:00:01Z") == 1_000_000_000
    assert _rfc3339_to_ns("1970-01-01T00:00:00.5Z") == 500_000_000
    assert _rfc3339_to_ns("1970-01-01T00:00:00.123456789Z") == 123_456_000


def test_rfc3339_to_ns_returns_zero_for_sentinel_and_garbage():
    """Verify _rfc3339_to_ns returns 0 for Nomad's zero sentinel, blanks, and unparsable input."""
    # Given the zero sentinel Nomad emits before a task starts, plus blank and garbage input
    # When parsing each
    # Then all collapse to 0 so the CreateTime fallback applies
    assert _rfc3339_to_ns("0001-01-01T00:00:00Z") == 0
    assert _rfc3339_to_ns("") == 0
    assert _rfc3339_to_ns("not-a-timestamp") == 0


def test_rfc3339_to_ns_returns_zero_for_offsetless_timestamp():
    """Verify _rfc3339_to_ns returns 0 for a timestamp with no UTC offset instead of raising."""
    # Given a timestamp Python parses into a naive datetime (no trailing Z or offset)
    # When parsing it
    # Then it collapses to 0 rather than blowing up on naive/aware arithmetic
    assert _rfc3339_to_ns("2024-06-01T12:00:00") == 0
    assert _rfc3339_to_ns("2024-06-01T12:00:00.123456789") == 0


def test_rfc3339_to_ns_honors_non_utc_offsets():
    """Verify _rfc3339_to_ns normalizes a non-UTC offset to the correct unix instant."""
    # Given the same instant expressed in UTC and in a +05:00 offset
    # When parsing both
    # Then they resolve to identical nanoseconds
    assert _rfc3339_to_ns("1970-01-01T05:00:01+05:00") == 1_000_000_000


def test_alloc_run_start_ns_prefers_earliest_task_started_at():
    """Verify the run-start anchor is the earliest task StartedAt, not the alloc CreateTime."""
    # Given an alloc created earlier whose two tasks started at different later times
    alloc = _alloc(
        create_time=1_000_000_000,
        task_states={
            "main": _task_state(started_at="1970-01-01T00:00:05Z"),
            "sidecar": _task_state(started_at="1970-01-01T00:00:03Z"),
        },
    )

    # When computing the run-start anchor
    # Then the earliest task start wins over the alloc CreateTime
    assert _alloc_run_start_ns(alloc) == 3_000_000_000


def test_alloc_run_start_ns_falls_back_to_create_time():
    """Verify the run-start anchor falls back to CreateTime when no task has started."""
    # Given an alloc whose tasks carry only the zero sentinel StartedAt
    alloc = _alloc(
        create_time=7_000_000_000,
        task_states={"main": _task_state(state="pending", started_at="0001-01-01T00:00:00Z")},
    )

    # When computing the run-start anchor
    # Then it falls back to the alloc CreateTime
    assert _alloc_run_start_ns(alloc) == 7_000_000_000


def test_build_host_report_one_panel_per_node_sorted():
    """Verify build_host_report returns one panel per client node, sorted by name."""
    # Given three client nodes in unsorted order carrying identifying metadata
    nodes = [
        _node(name="zeta", address="10.0.0.3"),
        _node(name="alpha", address="10.0.0.1"),
        _node(name="mid", address="10.0.0.2"),
    ]

    # When building the host report
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[])

    # Then there is one panel per node, alphabetical, carrying node identity
    assert [p.name for p in panels] == ["alpha", "mid", "zeta"]
    assert panels[0].address == "10.0.0.1"
    assert panels[0].link_id == "alpha"
    assert panels[0].jobs == []


def test_build_host_report_groups_jobs_by_node_with_type_and_group():
    """Verify each host panel lists its allocs with job name, type, task group, and status."""
    # Given two nodes and jobs of differing types placed across them
    nodes = [_node(name="srv1"), _node(name="srv2")]
    jobs = [_job(name="web", status="running"), _job(name="cron", status="running")]
    allocs = [
        _alloc(name="w1", job_id="web", node_id="srv1", task_group="frontend"),
        _alloc(name="c1", job_id="cron", node_id="srv2", task_group="batch"),
    ]

    # When building the host report with cron typed as a batch job
    jobs[1] = JobListStub(
        id="cron",
        name="cron",
        type="batch",
        status="running",
        priority=50,
        namespace="default",
        create_index=1,
        modify_index=2,
    )
    panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs)

    # Then each node's panel carries the job rows placed on it, with type resolved from the job
    by_name = {p.name: p for p in panels}
    assert [(r.name, r.job_type, r.group, r.status) for r in by_name["srv1"].jobs] == [
        ("web", "service", "frontend", "running")
    ]
    assert [(r.name, r.job_type, r.group) for r in by_name["srv2"].jobs] == [
        ("cron", "batch", "batch")
    ]


def test_build_host_report_filters_allocs_like_default_view():
    """Verify host job rows include running/pending/failed-unreplaced and exclude the rest."""
    # Given one node carrying every allocation shape the default view distinguishes
    nodes = [_node(name="srv1")]
    jobs = [_job(name="web")]
    allocs = [
        _alloc(name="run", job_id="web", node_id="srv1", client_status="running"),
        _alloc(name="pend", job_id="web", node_id="srv1", client_status="pending"),
        _alloc(name="fail", job_id="web", node_id="srv1", client_status="failed"),
        # excluded: intentionally retired corpse
        _alloc(
            name="retired",
            job_id="web",
            node_id="srv1",
            client_status="failed",
            desired_status="stop",
        ),
        # excluded: failed corpse already replaced by a running alloc
        _alloc(
            name="replaced",
            job_id="web",
            node_id="srv1",
            client_status="failed",
            next_allocation="run",
        ),
        # excluded: cleanly-finished batch alloc
        _alloc(name="done", job_id="web", node_id="srv1", client_status="complete"),
    ]

    # When building the host report
    panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs)

    # Then only running, pending, and the unreplaced failure remain
    statuses = sorted(r.status for r in panels[0].jobs)
    assert statuses == ["failed", "pending", "running"]


def test_build_host_report_uses_run_start_anchor():
    """Verify a host job row's uptime anchor is the alloc's earliest task start."""
    # Given a running alloc whose task started after the alloc was created
    nodes = [_node(name="srv1")]
    jobs = [_job(name="web")]
    allocs = [
        _alloc(
            name="w1",
            job_id="web",
            node_id="srv1",
            create_time=1_000_000_000,
            task_states={"main": _task_state(started_at="1970-01-01T00:00:09Z")},
        )
    ]

    # When building the host report
    panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs)

    # Then the row carries the task start (not the earlier create time) as its anchor
    assert panels[0].jobs[0].run_start_ns == 9_000_000_000


def test_build_host_report_reflects_node_health_metadata():
    """Verify a host panel exposes status, version, and an eligibility flag from its node."""
    # Given a draining, ineligible node
    nodes = [_node(name="srv1", status="ready", drain=True, eligibility="ineligible")]

    # When building the host report
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[])

    # Then the panel reports the node status/version and marks it not eligible
    assert panels[0].status == "ready"
    assert panels[0].version == "1.9.0"
    assert panels[0].eligible is False


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


def test_build_report_degrades_job_with_unreplaced_failed_alloc():
    """Verify a running job whose latest alloc on a node failed with no replacement is degraded."""
    # Given a system job (like diun) whose retry on one node keeps failing: a superseded failed
    # attempt (points to a next alloc) plus the head failed attempt (no replacement)
    nodes = [_node(name="srv1"), _node(name="srv2")]
    jobs = [_job(name="diun", status="running"), _job(name="web", status="running")]
    allocs = [
        _alloc(name="d1", job_id="diun", node_id="srv1", client_status="running"),
        _alloc(
            name="d-old",
            job_id="diun",
            node_id="srv2",
            client_status="failed",
            next_allocation="d-head",
        ),
        _alloc(name="d-head", job_id="diun", node_id="srv2", client_status="failed"),
        _alloc(name="w1", job_id="web", node_id="srv1", client_status="running"),
    ]

    # When building the report
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # Then the unreplaced failure degrades diun and drops it from the running count
    assert report.job_statuses["diun"] == "degraded"
    assert report.job_statuses["web"] == "running"
    assert report.jobs_running == 1
    # And the banner agrees: the health verdict is degraded and only the unreplaced head counts
    # as failed (the superseded d-old corpse is ignored, so it reads 1 failed, not 2)
    assert report.health is Health.DEGRADED
    assert report.allocs_failed == 1


def test_build_report_ignores_recovered_failed_alloc():
    """Verify a failed alloc that Nomad rescheduled onto a running replacement is not degraded."""
    # Given a job (scenario 2: stopped on a node then restarted) whose failed alloc was superseded
    # by a now-running replacement, so the failed corpse points at a next allocation
    nodes = [_node(name="srv1")]
    jobs = [_job(name="web", status="running")]
    allocs = [
        _alloc(
            name="w-old",
            job_id="web",
            node_id="srv1",
            client_status="failed",
            next_allocation="w-new",
        ),
        _alloc(name="w-new", job_id="web", node_id="srv1", client_status="running"),
    ]

    # When building the report
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # Then the recovered failure is ignored and the job stays running
    assert report.job_statuses["web"] == "running"
    assert report.jobs_running == 1
    # And the banner agrees rather than raising a false alarm: no failed count, health stays green
    assert report.allocs_failed == 0
    assert report.health is Health.HEALTHY


def test_build_report_keeps_running_status_when_failed_alloc_is_retired():
    """Verify a failed alloc Nomad has intentionally stopped does not degrade its job."""
    # Given a running job whose failed alloc was intentionally stopped (desired_status stop)
    nodes = [_node(name="srv1")]
    jobs = [_job(name="web", status="running")]
    allocs = [
        _alloc(name="w1", job_id="web", node_id="srv1", client_status="running"),
        _alloc(
            name="w0",
            job_id="web",
            node_id="srv1",
            client_status="failed",
            desired_status="stop",
        ),
    ]

    # When building the report
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # Then the retired corpse is ignored and the job stays running
    assert report.job_statuses["web"] == "running"
    assert report.jobs_running == 1


def test_render_report_jobs_panel_shows_degraded_for_unreplaced_failure():
    """Verify the jobs panel renders a degraded row when a job's latest alloc failed unreplaced."""
    # Given a running job with a failed head allocation Nomad has not replaced
    nodes = [_node(name="srv1"), _node(name="srv2")]
    jobs = [_job(name="diun", status="running")]
    allocs = [
        _alloc(name="d1", job_id="diun", node_id="srv1", client_status="running"),
        _alloc(name="d2", job_id="diun", node_id="srv2", client_status="failed"),
    ]
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # When rendering it
    text = _render_to_text(report)

    # Then the diun row shows degraded rather than running
    assert "degraded" in text


def test_render_report_tints_degraded_job_name_yellow():
    """Verify a degraded job's name is tinted yellow to match its status, while others are not."""
    # Given a degraded job (diun) alongside a healthy running job (web)
    nodes = [_node(name="srv1"), _node(name="srv2")]
    jobs = [_job(name="diun", status="running"), _job(name="web", status="running")]
    allocs = [
        _alloc(name="d1", job_id="diun", node_id="srv1", client_status="running"),
        _alloc(name="d2", job_id="diun", node_id="srv2", client_status="failed"),
        _alloc(name="w1", job_id="web", node_id="srv1", client_status="running"),
    ]
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # When rendering with ANSI styles retained (\x1b[33m is the yellow SGR code)
    styled = _render_to_styled_text(report)

    # Then the degraded job's name is wrapped in yellow, while the healthy job's name is not tinted
    assert "\x1b[33mdiun\x1b[0m" in styled
    assert "\x1b[33mweb" not in styled


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


def test_build_report_ignores_retired_failed_alloc():
    """Verify a failed corpse Nomad has retired (desired_status stop) does not degrade health."""
    # Given a failed allocation that Nomad has already rescheduled away (desired_status "stop")
    report = build_report(
        nodes=[_node()],
        jobs=[_job()],
        allocs=[
            _alloc(name="live", client_status="running"),
            _alloc(name="corpse", client_status="failed", desired_status="stop"),
        ],
        config=_CONFIG,
    )

    # Then the corpse is excluded from the failed count and the cluster stays healthy
    assert report.allocs_failed == 0
    assert report.health is Health.HEALTHY


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


def _capture_render(report: StatusReport) -> Console:
    """Render a report through a recording console and return that console."""
    capture = Console(theme=pp.THEME, record=True, force_terminal=True, width=100)
    emitter = pp.Emitter(console=capture, err_console=capture)
    original = pp.get_default()
    pp.set_default(emitter)
    try:
        from nd.commands.status import render_report

        render_report(report)
    finally:
        pp.set_default(original)
    return capture


def _render_to_text(report: StatusReport) -> str:
    """Render a report and return the captured plain text (styles stripped)."""
    return _capture_render(report).export_text()


def _render_to_styled_text(report: StatusReport) -> str:
    """Render a report and return the captured text with ANSI style codes retained."""
    return _capture_render(report).export_text(styles=True)


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
    assert "DEPLOYS" in text
    assert "0 active" in text
    assert "EVALS" in text
    assert "0 blocked" in text


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
    router.get(f"{_ADDR}/v1/volumes", params={"type": "host"}).respond(json=[])


def test_collect_aggregates_all_endpoints(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify _collect fetches every endpoint and returns a populated report."""
    # Given a fully mocked cluster and an isolated config environment
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _mock_all(httpx2_mock)

    # When collecting status
    from nd.commands.status import _collect

    report, _panels = asyncio.run(_collect(verbose=0))

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


def test_collect_returns_report_and_host_panels(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify _collect returns both the status report and one host panel per client node."""
    # Given a fully mocked cluster and an isolated config environment
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _mock_all(httpx2_mock)

    # When collecting status
    from nd.commands.status import _collect

    report, panels = asyncio.run(_collect(verbose=0))

    # Then the report is populated and a host panel exists for the mocked node
    assert report.health is Health.HEALTHY
    assert [p.name for p in panels] == ["srv1"]
    assert [r.name for r in panels[0].jobs] == ["web"]


def test_status_command_hosts_flag_uses_host_view(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, mocker
):
    """Verify `nd status --hosts` renders the host view instead of the default dashboard."""
    # Given a fully mocked cluster and both render paths patched
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _mock_all(httpx2_mock)
    render_hosts = mocker.patch("nd.commands.status.command.render_hosts", autospec=True)
    render_report = mocker.patch("nd.commands.status.command.render_report", autospec=True)

    # When invoking the status sub-app with --hosts
    from nd.commands import status

    result = CliRunner().invoke(status.app, ["--hosts"])

    # Then it exits cleanly and dispatches to the host view only
    assert result.exit_code == 0
    render_hosts.assert_called_once()
    render_report.assert_not_called()


def test_status_command_default_uses_dashboard_view(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, mocker
):
    """Verify `nd status` with no flag renders the default dashboard, not the host view."""
    # Given a fully mocked cluster and both render paths patched
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _mock_all(httpx2_mock)
    render_hosts = mocker.patch("nd.commands.status.command.render_hosts", autospec=True)
    render_report = mocker.patch("nd.commands.status.command.render_report", autospec=True)

    # When invoking the status sub-app with no flag
    from nd.commands import status

    result = CliRunner().invoke(status.app, [])

    # Then it exits cleanly and dispatches to the default dashboard only
    assert result.exit_code == 0
    render_report.assert_called_once()
    render_hosts.assert_not_called()


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


def test_build_report_counts_volumes() -> None:
    """Verify build_report groups by distinct volume name for the total count."""
    # Given two registrations of the same volume name on different nodes
    vols = [
        HostVolumeListStub(id="data:n1", name="data", node_id="n1"),
        HostVolumeListStub(id="data:n2", name="data", node_id="n2"),
    ]
    nodes = [_node(name="n1"), _node(name="n2")]

    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG, volumes=vols)

    # Then volumes_total counts distinct volume names, not registrations
    assert report.volumes_total == 1
    # And volume_rows has one aggregated row with both node names
    assert len(report.volume_rows) == 1
    assert report.volume_rows[0].name == "data"
    assert sorted(report.volume_rows[0].nodes) == ["n1", "n2"]


def test_build_report_volume_rows_resolve_node_names() -> None:
    """Verify volume_rows carry resolved node names, not raw node IDs."""
    # Given a volume whose node_id maps to a display name
    vols = [HostVolumeListStub(id="data:n1", name="data", node_id="n1", state="ready")]
    nodes = [_node(name="n1")]

    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG, volumes=vols)

    # Then the row's nodes list contains the display name
    assert report.volume_rows[0].nodes == ["n1"]
    assert report.volume_rows[0].state == "ready"


def _capture_render_hosts(report: StatusReport, panels, *, width: int = 100) -> Console:
    """Render the host view through a recording console at a given width and return it."""
    capture = Console(theme=pp.THEME, record=True, force_terminal=True, width=width)
    emitter = pp.Emitter(console=capture, err_console=capture)
    original = pp.get_default()
    pp.set_default(emitter)
    try:
        from nd.commands.status import render_hosts

        render_hosts(report, panels)
    finally:
        pp.set_default(original)
    return capture


def test_render_hosts_shows_banner_and_per_host_jobs() -> None:
    """Verify the host view keeps the banner and renders each host's jobs (no volumes)."""
    # Given two nodes and a job placed on one
    nodes = [_node(name="alpha", address="10.0.0.1"), _node(name="beta", address="10.0.0.2")]
    jobs = [_job(name="web")]
    allocs = [
        _alloc(
            name="w1",
            job_id="web",
            node_id="alpha",
            task_group="frontend",
            create_time=1_000_000_000,
        )
    ]
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)
    panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs)

    # When rendering the host view
    text = _capture_render_hosts(report, panels).export_text()

    # Then the banner verdict, both host names, and the job row's columns appear
    assert "HEALTHY" in text
    assert "alpha" in text
    assert "beta" in text
    assert "TYPE" in text
    assert "UPTIME" in text
    assert "web" in text
    # And the host view carries neither a Volumes sub-table nor a GROUP column
    assert "Volumes" not in text
    assert "GROUP" not in text


def test_render_hosts_shows_host_address_in_panel_title() -> None:
    """Verify each host panel titles itself with the node's address alongside its name."""
    # Given two nodes on distinct addresses
    nodes = [_node(name="alpha", address="10.0.0.11"), _node(name="beta", address="10.0.0.12")]
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG)
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[])

    # When rendering the host view
    text = _capture_render_hosts(report, panels).export_text()

    # Then both addresses appear, as they do in the default view's Nodes panel
    assert "10.0.0.11" in text
    assert "10.0.0.12" in text


def test_render_hosts_shows_placeholder_for_empty_host() -> None:
    """Verify a host with no allocs still renders with a dim jobs placeholder."""
    # Given a node with nothing placed on it
    nodes = [_node(name="alpha")]
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG)
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[])

    # When rendering the host view
    text = _capture_render_hosts(report, panels).export_text()

    # Then the panel still appears with an empty-state placeholder and no volumes section
    assert "alpha" in text
    assert "No jobs" in text
    assert "No volumes" not in text


def test_render_hosts_shows_activity_panel_when_present() -> None:
    """Verify the host view still renders the Activity panel for in-progress work."""
    # Given an active deployment and a blocked evaluation
    nodes = [_node(name="alpha")]
    report = build_report(
        nodes=nodes,
        jobs=[],
        allocs=[],
        config=_CONFIG,
        deployments=[_deployment(job_id="web", status="running")],
        evals=[_eval(job_id="api", status="blocked")],
    )
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[])

    # When rendering the host view
    text = _capture_render_hosts(report, panels).export_text()

    # Then the activity panel and its sections appear
    assert "Activity" in text
    assert "Deployments" in text


def test_render_hosts_places_panels_side_by_side_when_wide() -> None:
    """Verify a wide terminal lays two host panels into a shared row (two columns)."""
    # Given two nodes and a wide terminal
    nodes = [_node(name="alpha"), _node(name="beta")]
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG)
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[])

    # When rendering at a width above the two-column threshold
    text = _capture_render_hosts(report, panels, width=160).export_text()

    # Then both host titles share a line, proving they render side by side
    assert any("alpha" in line and "beta" in line for line in text.splitlines())


def test_render_hosts_stacks_panels_when_narrow() -> None:
    """Verify a narrow terminal stacks host panels in a single column."""
    # Given two nodes and a narrow terminal
    nodes = [_node(name="alpha"), _node(name="beta")]
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG)
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[])

    # When rendering at a width below the two-column threshold
    text = _capture_render_hosts(report, panels, width=90).export_text()

    # Then no single line carries both titles, but both panels are present
    assert not any("alpha" in line and "beta" in line for line in text.splitlines())
    assert "alpha" in text
    assert "beta" in text


def test_render_report_shows_volumes_panel() -> None:
    """Verify the dashboard renders a Volumes panel listing volumes with node names."""
    # Given a report with one volume registered on two nodes
    vols = [
        HostVolumeListStub(id="data:n1", name="data", node_id="n1", state="ready"),
        HostVolumeListStub(id="data:n2", name="data", node_id="n2", state="ready"),
    ]
    nodes = [_node(name="n1"), _node(name="n2")]
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG, volumes=vols)

    # When rendering it
    text = _render_to_text(report)

    # Then the volume name and both node names appear under a Volumes heading
    assert "Volumes" in text
    assert "data" in text
    assert "n1" in text
    assert "n2" in text
