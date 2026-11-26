"""Tests for status report aggregation."""

import pytest

from nd.commands.status.report import (
    Health,
    ServerInfo,
    _alloc_run_start_ns,
    build_host_report,
    build_report,
    correlate_nodes,
)
from nd.nomad.config import NomadConfig
from nd.nomad.models.agent import AgentMember
from nd.nomad.models.allocation import AllocListStub, TaskState
from nd.nomad.models.node import NodeListStub
from tests.builders import (
    agent_member,
    alloc_stub,
    deployment,
    eval_stub,
    host_volume_stub,
    job_stub,
    node_stub,
    task_state,
)
from tests.helpers import NOMAD_TEST_ADDR

_CONFIG = NomadConfig(address=NOMAD_TEST_ADDR, region="global", namespace="default")


@pytest.mark.parametrize(
    ("task_states", "expected_ns"),
    [
        pytest.param(
            {
                "main": task_state(started_at="1970-01-01T00:00:05Z"),
                "sidecar": task_state(started_at="1970-01-01T00:00:03Z"),
            },
            3_000_000_000,
            id="earliest-task-start",
        ),
        pytest.param(
            {"main": task_state("pending", started_at="0001-01-01T00:00:00Z")},
            1_000_000_000,
            id="no-task-started-falls-back-to-create-time",
        ),
    ],
)
def test_alloc_run_start_ns_anchor(task_states: dict[str, TaskState], expected_ns: int) -> None:
    """Verify the run-start anchor is the earliest task start, else the alloc CreateTime."""
    # Given an alloc created at 1s whose tasks carry the given StartedAt values
    alloc = alloc_stub(create_time=1_000_000_000, task_states=task_states)

    # When computing the run-start anchor
    # Then the earliest real task start wins, and the zero sentinel falls back to CreateTime
    assert _alloc_run_start_ns(alloc) == expected_ns


def test_build_host_report_one_panel_per_node_sorted() -> None:
    """Verify build_host_report returns one panel per client node, sorted by name."""
    # Given three client nodes in unsorted order carrying identifying metadata
    nodes = [
        node_stub("zeta", address="10.0.0.3"),
        node_stub("alpha", address="10.0.0.1"),
        node_stub("mid", address="10.0.0.2"),
    ]

    # When building the host report
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[], servers=[])

    # Then there is one panel per node, alphabetical, carrying node identity
    assert [p.name for p in panels] == ["alpha", "mid", "zeta"]
    assert panels[0].address == "10.0.0.1"
    assert panels[0].link_id == "alpha"
    assert panels[0].jobs == []


def test_build_host_report_includes_server_only_hosts_with_roles() -> None:
    """Verify servers without a client agent get a panel and co-located servers carry a role."""
    # Given a leader that also runs a client with a job, and a server with no client agent
    nodes = [node_stub("mf1", address="10.0.0.1")]
    jobs = [job_stub("web")]
    allocs = [alloc_stub("w1", job_id="web", node_id="mf1")]
    servers = [
        ServerInfo(name="mf1", addr="10.0.0.1", status="alive", version="2.0.3", is_leader=True),
        ServerInfo(name="ctl", addr="10.0.0.5", status="alive", version="2.0.3", is_leader=False),
    ]

    # When building the host report with the server members
    panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs, servers=servers)

    # Then both machines appear: the leader keeps its jobs, the server-only host has none
    by_name = {p.name: p for p in panels}
    assert [p.name for p in panels] == ["ctl", "mf1"]
    assert by_name["mf1"].role == "leader"
    assert [r.name for r in by_name["mf1"].jobs] == ["web"]
    assert by_name["ctl"].role == "server"
    assert by_name["ctl"].link_id is None
    assert by_name["ctl"].jobs == []


def test_build_host_report_groups_jobs_by_node_with_type_and_group() -> None:
    """Verify each host panel lists its allocs with job name, type, task group, and status."""
    # Given two nodes, a service job and a batch job, placed one per node
    nodes = [node_stub("srv1"), node_stub("srv2")]
    jobs = [job_stub("web"), job_stub("cron", job_type="batch")]
    allocs = [
        alloc_stub("w1", job_id="web", node_id="srv1", task_group="frontend"),
        alloc_stub("c1", job_id="cron", node_id="srv2", task_group="batch"),
    ]

    # When building the host report
    panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs, servers=[])

    # Then each node's panel carries the job rows placed on it, with type resolved from the job
    by_name = {p.name: p for p in panels}
    assert [(r.name, r.job_type, r.group, r.status) for r in by_name["srv1"].jobs] == [
        ("web", "service", "frontend", "running")
    ]
    assert [(r.name, r.job_type, r.group) for r in by_name["srv2"].jobs] == [
        ("cron", "batch", "batch")
    ]


def test_build_host_report_filters_allocs_like_default_view() -> None:
    """Verify host job rows include running/pending/failed-unreplaced and exclude the rest."""
    # Given one node carrying every allocation shape the default view distinguishes
    nodes = [node_stub("srv1")]
    jobs = [job_stub("web")]
    allocs = [
        alloc_stub("run", node_id="srv1", client_status="running"),
        alloc_stub("pend", node_id="srv1", client_status="pending"),
        alloc_stub("fail", node_id="srv1", client_status="failed"),
        # excluded: intentionally retired corpse
        alloc_stub("retired", node_id="srv1", client_status="failed", desired_status="stop"),
        # excluded: failed corpse already replaced by a running alloc
        alloc_stub("replaced", node_id="srv1", client_status="failed", next_allocation="run"),
        # excluded: cleanly-finished batch alloc
        alloc_stub("done", node_id="srv1", client_status="complete"),
    ]

    # When building the host report
    panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs, servers=[])

    # Then only running, pending, and the unreplaced failure remain
    statuses = sorted(r.status for r in panels[0].jobs)
    assert statuses == ["failed", "pending", "running"]


def test_build_host_report_uses_run_start_anchor() -> None:
    """Verify a host job row's uptime anchor is the alloc's earliest task start."""
    # Given a running alloc whose task started after the alloc was created
    nodes = [node_stub("srv1")]
    jobs = [job_stub("web")]
    allocs = [
        alloc_stub(
            "w1",
            node_id="srv1",
            create_time=1_000_000_000,
            task_states={"main": task_state(started_at="1970-01-01T00:00:09Z")},
        )
    ]

    # When building the host report
    panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs, servers=[])

    # Then the row carries the task start (not the earlier create time) as its anchor
    assert panels[0].jobs[0].run_start_ns == 9_000_000_000


def test_build_host_report_reflects_node_health_metadata() -> None:
    """Verify a host panel exposes status, version, and an eligibility flag from its node."""
    # Given a draining, ineligible node
    nodes = [node_stub("srv1", status="ready", drain=True, eligibility="ineligible")]

    # When building the host report
    panels = build_host_report(nodes=nodes, jobs=[], allocs=[], servers=[])

    # Then the panel reports the node status/version and marks it not eligible
    assert panels[0].status == "ready"
    assert panels[0].version == "1.9.0"
    assert panels[0].eligible is False


def test_build_report_all_healthy() -> None:
    """Verify a clean cluster reports HEALTHY and retains full counts."""
    # Given all-ready nodes, running jobs, and running allocations
    nodes = [node_stub("srv1"), node_stub("srv2")]
    jobs = [job_stub("web"), job_stub("api")]
    allocs = [alloc_stub("a1"), alloc_stub("a2", client_status="complete")]

    # When building the report
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # Then it is healthy with full counts and lists
    assert report.health is Health.HEALTHY
    assert report.nodes_ready == 2
    assert report.nodes_total == 2
    assert report.jobs_total == 2
    assert report.jobs_running == 2
    assert report.allocs_running == 1


def test_build_report_counts_active_allocs_per_node() -> None:
    """Verify per-node alloc counts include running/pending but exclude terminal allocs."""
    # Given two nodes and a mix of active and terminal allocations across them
    nodes = [node_stub("srv1"), node_stub("srv2")]
    allocs = [
        alloc_stub("a1", node_id="srv1", client_status="running"),
        alloc_stub("a2", node_id="srv1", client_status="pending"),
        alloc_stub("a3", node_id="srv1", client_status="complete"),
        alloc_stub("a4", node_id="srv2", client_status="running"),
    ]

    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=allocs, config=_CONFIG)

    # Then only active (running + pending) allocs are counted, keyed by node id
    assert report.node_alloc_counts == {"srv1": 2, "srv2": 1}


def test_build_report_maps_jobs_to_node_names() -> None:
    """Verify each job maps to the sorted, de-duplicated names of its active alloc nodes."""
    # Given nodes whose ids differ from their display names and active allocs spread across them
    nodes = [
        node_stub("zeta", node_id="id-z", address="10.0.0.1"),
        node_stub("alpha", node_id="id-a", address="10.0.0.2"),
    ]
    allocs = [
        alloc_stub("w1", job_id="web", node_id="id-z", client_status="running"),
        alloc_stub("w2", job_id="web", node_id="id-a", client_status="running"),
        alloc_stub("w3", job_id="web", node_id="id-z", client_status="running"),
        alloc_stub("w4", job_id="web", node_id="id-a", client_status="complete"),
        alloc_stub("a1", job_id="api", node_id="id-a", client_status="pending"),
    ]

    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=allocs, config=_CONFIG)

    # Then job nodes are resolved to names, de-duplicated and sorted; terminal allocs excluded
    assert report.job_nodes == {"web": ["alpha", "zeta"], "api": ["alpha"]}


def test_build_report_degrades_job_with_unreplaced_failed_alloc() -> None:
    """Verify a running job whose latest alloc on a node failed with no replacement is degraded."""
    # Given a system job whose retry on one node keeps failing: a superseded failed attempt
    # (points to a next alloc) plus the head failed attempt (no replacement)
    nodes = [node_stub("srv1"), node_stub("srv2")]
    jobs = [job_stub("diun"), job_stub("web")]
    allocs = [
        alloc_stub("d1", job_id="diun", node_id="srv1", client_status="running"),
        alloc_stub(
            "d-old", job_id="diun", node_id="srv2", client_status="failed", next_allocation="d-head"
        ),
        alloc_stub("d-head", job_id="diun", node_id="srv2", client_status="failed"),
        alloc_stub("w1", job_id="web", node_id="srv1", client_status="running"),
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


@pytest.mark.parametrize(
    "corpse",
    [
        pytest.param(
            alloc_stub("w-old", node_id="srv1", client_status="failed", next_allocation="w-new"),
            id="replaced",
        ),
        pytest.param(
            alloc_stub("w-old", node_id="srv1", client_status="failed", desired_status="stop"),
            id="retired",
        ),
    ],
)
def test_build_report_ignores_recovered_failed_alloc(corpse: AllocListStub) -> None:
    """Verify a failed alloc Nomad replaced or retired neither degrades its job nor the cluster."""
    # Given a running job whose failed alloc was replaced or intentionally stopped
    nodes = [node_stub("srv1")]
    jobs = [job_stub("web")]
    allocs = [corpse, alloc_stub("w-new", node_id="srv1", client_status="running")]

    # When building the report
    report = build_report(nodes=nodes, jobs=jobs, allocs=allocs, config=_CONFIG)

    # Then the corpse is ignored: the job stays running and the banner raises no false alarm
    assert report.job_statuses["web"] == "running"
    assert report.jobs_running == 1
    assert report.allocs_failed == 0
    assert report.health is Health.HEALTHY


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        pytest.param(
            NomadConfig(address="http://nomad.test:4646/"),
            "http://nomad.test:4646",
            id="defaults-to-address",
        ),
        pytest.param(
            NomadConfig(address="http://10.0.0.1:4646", ui_url="https://nomad.example.org/"),
            "https://nomad.example.org",
            id="config-override",
        ),
    ],
)
def test_build_report_ui_url(config: NomadConfig, expected: str) -> None:
    """Verify the UI base URL is the configured ui_url, else the API address, slash trimmed."""
    # When building the report
    report = build_report(nodes=[], jobs=[], allocs=[], config=config)

    # Then the UI base URL is resolved with any trailing slash trimmed
    assert report.ui_url == expected


def test_build_report_sorts_everything_alphabetically() -> None:
    """Verify nodes, jobs, and servers are sorted by name."""
    # Given unsorted nodes, jobs, and servers
    nodes = [node_stub("zeta"), node_stub("alpha"), node_stub("mid")]
    jobs = [job_stub("web"), job_stub("api"), job_stub("db")]
    members = [
        agent_member("zeta.global"),
        agent_member("alpha.global"),
        agent_member("mid.global"),
    ]

    # When building the report
    report = build_report(nodes=nodes, jobs=jobs, allocs=[], config=_CONFIG, members=members)

    # Then each list is alphabetical by name
    assert [n.name for n in report.nodes] == ["alpha", "mid", "zeta"]
    assert [j.name for j in report.jobs] == ["api", "db", "web"]
    assert [s.name for s in report.servers] == ["alpha", "mid", "zeta"]


def test_build_report_resolves_servers_and_leader() -> None:
    """Verify server members are summarized and the leader is identified by address."""
    # Given three alive servers and a leader address pointing at one of them
    members = [
        agent_member("mf1.global", addr="10.0.0.1"),
        agent_member("rpi1.global", addr="10.0.0.2"),
        agent_member("rpi2.global", addr="10.0.0.3"),
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


def test_build_report_matches_leader_by_rpc_tag_when_serf_addr_differs() -> None:
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


@pytest.mark.parametrize(
    ("nodes", "allocs", "expected"),
    [
        pytest.param(
            [node_stub("srv1"), node_stub("srv2", status="down")],
            [],
            Health.CRITICAL,
            id="down-node",
        ),
        pytest.param(
            [node_stub("srv1", drain=True, eligibility="ineligible")],
            [],
            Health.DEGRADED,
            id="draining-node",
        ),
        pytest.param([], [alloc_stub(client_status="lost")], Health.DEGRADED, id="lost-alloc"),
    ],
)
def test_build_report_health_verdict(
    nodes: list[NodeListStub], allocs: list[AllocListStub], expected: Health
) -> None:
    """Verify a down node is critical, and a draining node or lost alloc degrades the cluster."""
    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=allocs, config=_CONFIG)

    # Then the verdict matches the worst problem present
    assert report.health is expected


def test_build_report_critical_when_no_leader() -> None:
    """Verify servers present without an elected leader is CRITICAL."""
    # Given servers but no leader address
    members = [agent_member("mf1.global", addr="10.0.0.1")]

    # When building the report with an empty leader
    report = build_report(nodes=[], jobs=[], allocs=[], config=_CONFIG, members=members, leader="")

    # Then the cluster is critical
    assert report.leader_name is None
    assert report.health is Health.CRITICAL


def test_build_report_degraded_when_server_not_alive() -> None:
    """Verify a non-alive server degrades the cluster."""
    # Given a failed follower alongside the alive leader
    members = [
        agent_member("mf1.global", addr="10.0.0.1"),
        agent_member("rpi1.global", addr="10.0.0.2", status="failed"),
    ]

    # When building the report
    report = build_report(
        nodes=[], jobs=[], allocs=[], config=_CONFIG, members=members, leader="10.0.0.1:4647"
    )

    # Then the cluster is degraded
    assert report.servers_alive == 1
    assert report.health is Health.DEGRADED


def test_build_report_flags_active_deployments_and_problem_evals() -> None:
    """Verify running deployments and blocked/queued evals are surfaced."""
    # Given a healthy single-server cluster with an active deploy and a blocked eval
    members = [agent_member(addr="10.0.0.1")]
    deployments = [deployment("web", status="running"), deployment("db", status="successful")]
    evals = [
        eval_stub("web", status="blocked"),
        eval_stub("api", status="pending", queued={"group": 2}),
        eval_stub("stale", status="complete", queued={"group": 5}),
        eval_stub("db", status="complete"),
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


def test_build_report_degraded_on_dead_job() -> None:
    """Verify a non-running job degrades the cluster while all jobs stay listed."""
    # Given a mix of running and dead jobs
    jobs = [job_stub("web"), job_stub("batch", status="dead")]

    # When building the report
    report = build_report(nodes=[], jobs=jobs, allocs=[], config=_CONFIG)

    # Then every job is listed and the verdict is degraded
    assert [j.name for j in report.jobs] == ["batch", "web"]
    assert report.jobs_total == 2
    assert report.jobs_running == 1
    assert report.health is Health.DEGRADED


def test_build_report_degraded_on_failed_alloc() -> None:
    """Verify a failed allocation degrades the cluster and is counted."""
    # Given running, complete, and failed allocations
    allocs = [
        alloc_stub("a1"),
        alloc_stub("a2", client_status="complete"),
        alloc_stub("a3", client_status="failed"),
    ]

    # When building the report
    report = build_report(nodes=[], jobs=[], allocs=allocs, config=_CONFIG)

    # Then failure counts are tracked and the cluster is degraded
    assert report.allocs_failed == 1
    assert report.allocs_running == 1
    assert report.health is Health.DEGRADED


@pytest.mark.parametrize(
    ("states", "expected_state"),
    [
        pytest.param(("ready", "ready"), "ready", id="same-state"),
        pytest.param(("ready", "pending"), "pending, ready", id="mixed-states"),
        pytest.param(("", ""), "-", id="no-state"),
    ],
)
def test_build_report_aggregates_volumes_by_name(
    states: tuple[str, str], expected_state: str
) -> None:
    """Verify volumes group by distinct name, with resolved node names and joined states."""
    # Given two registrations of the same volume name on different nodes
    vols = [
        host_volume_stub("data", node_id="n1", state=states[0]),
        host_volume_stub("data", node_id="n2", state=states[1]),
    ]
    nodes = [node_stub("n1"), node_stub("n2")]

    # When building the report
    report = build_report(nodes=nodes, jobs=[], allocs=[], config=_CONFIG, volumes=vols)

    # Then volumes_total counts distinct volume names, not registrations
    assert report.volumes_total == 1
    # And volume_rows has one aggregated row with both node names and the volume state
    assert len(report.volume_rows) == 1
    assert report.volume_rows[0].name == "data"
    assert sorted(report.volume_rows[0].nodes) == ["n1", "n2"]
    assert report.volume_rows[0].state == expected_state


def test_correlate_nodes_annotates_roles_and_appends_server_only() -> None:
    """Verify nodes get server roles by address and server-only hosts are appended."""
    # Given a leader host, a client-only host, and a server with no client node
    nodes = [node_stub("mf1", address="10.0.0.1"), node_stub("box", address="10.0.0.9")]
    servers = [
        ServerInfo(name="mf1", addr="10.0.0.1", status="alive", version="2.0.3", is_leader=True),
        ServerInfo(name="ghost", addr="10.0.0.5", status="alive", version="2.0.3", is_leader=False),
    ]

    # When correlating
    rows = correlate_nodes(nodes=nodes, servers=servers)

    # Then roles are assigned and the server-only host appears with no client link
    by_name = {r.name: r for r in rows}
    assert by_name["mf1"].role == "leader"
    assert by_name["box"].role == "client"
    assert by_name["ghost"].role == "server"
    assert by_name["ghost"].link_id is None


def test_correlate_nodes_matches_by_name_when_addresses_differ() -> None:
    """Verify a server folds into its client node by host name when addresses differ."""
    # Given a node and its server whose serf addr differs from the node HTTP address
    nodes = [node_stub("mf1", address="10.0.30.95")]
    servers = [
        ServerInfo(name="mf1", addr="10.0.0.1", status="alive", version="2.0.3", is_leader=True)
    ]

    # When correlating
    rows = correlate_nodes(nodes=nodes, servers=servers)

    # Then they merge into a single leader-annotated client row (no duplicate server row)
    assert len(rows) == 1
    assert rows[0].role == "leader"
    assert rows[0].link_id == "mf1"
