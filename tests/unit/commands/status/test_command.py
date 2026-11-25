"""Tests for the status command wiring and cluster collection."""

import asyncio

import pytest
import respx
from pytest_mock import MockerFixture

from nd import cli
from nd.commands import status
from nd.commands.status.command import _collect
from nd.commands.status.report import Health
from tests.builders import agent_member, alloc_stub, job_stub, node_stub, to_payload


@pytest.fixture
def mocked_cluster(httpx2_mock: respx.Router, nomad_env: str) -> None:
    """Mock every endpoint `nd status` reads: one node running one job, led by one server."""
    httpx2_mock.get(f"{nomad_env}/v1/nodes").respond(json=[to_payload(node_stub("srv1"))])
    httpx2_mock.get(f"{nomad_env}/v1/jobs").respond(json=[to_payload(job_stub("web"))])
    httpx2_mock.get(f"{nomad_env}/v1/allocations").respond(
        json=[to_payload(alloc_stub("a1", node_id="srv1"))]
    )
    httpx2_mock.get(f"{nomad_env}/v1/agent/members").respond(
        json={"Members": [to_payload(agent_member("srv1.global", build="1.9.0"))]}
    )
    httpx2_mock.get(f"{nomad_env}/v1/status/leader").respond(json="10.0.0.1:4647")
    httpx2_mock.get(f"{nomad_env}/v1/deployments").respond(json=[])
    httpx2_mock.get(f"{nomad_env}/v1/evaluations").respond(json=[])
    httpx2_mock.get(f"{nomad_env}/v1/volumes", params={"type": "host"}).respond(json=[])


@pytest.mark.usefixtures("mocked_cluster")
def test_collect_aggregates_all_endpoints() -> None:
    """Verify _collect fetches every endpoint and returns a populated report."""
    # Given a fully mocked cluster
    # When collecting status
    report, _panels = asyncio.run(_collect(verbose=0))

    # Then the report reflects the mocked data
    assert report.health is Health.HEALTHY
    assert report.nodes_total == 1
    assert report.jobs_running == 1
    assert report.allocs_running == 1
    assert report.servers_total == 1
    assert report.leader_name == "srv1"


@pytest.mark.usefixtures("mocked_cluster")
def test_collect_returns_report_and_host_panels() -> None:
    """Verify _collect returns both the status report and one host panel per client node."""
    # Given a fully mocked cluster
    # When collecting status for the host view
    report, panels = asyncio.run(_collect(verbose=0, hosts=True))

    # Then the report is populated and a host panel exists for the mocked node
    assert report.health is Health.HEALTHY
    assert [p.name for p in panels] == ["srv1"]
    assert [r.name for r in panels[0].jobs] == ["web"]


@pytest.mark.usefixtures("mocked_cluster")
def test_status_command_exits_zero(typer_runner) -> None:
    """Verify the status command runs end to end and exits successfully."""
    # Given a fully mocked cluster
    # When invoking the status sub-app
    result = typer_runner.invoke(status.app, [])

    # Then it exits cleanly
    assert result.exit_code == 0


@pytest.mark.usefixtures("mocked_cluster")
@pytest.mark.parametrize(
    ("args", "used_view", "unused_view"),
    [
        pytest.param([], "render_report", "render_hosts", id="default-dashboard"),
        pytest.param(["--hosts"], "render_hosts", "render_report", id="hosts-flag"),
    ],
)
def test_status_command_selects_view(
    mocker: MockerFixture, typer_runner, args: list[str], used_view: str, unused_view: str
) -> None:
    """Verify `nd status` renders the dashboard by default and the host view with --hosts."""
    # Given a fully mocked cluster and both render paths patched
    used = mocker.patch(f"nd.commands.status.command.{used_view}", autospec=True)
    unused = mocker.patch(f"nd.commands.status.command.{unused_view}", autospec=True)

    # When invoking the status sub-app
    result = typer_runner.invoke(status.app, args)

    # Then it exits cleanly and dispatches to the selected view only
    assert result.exit_code == 0
    used.assert_called_once()
    unused.assert_not_called()


@pytest.mark.usefixtures("mocked_cluster")
@pytest.mark.parametrize("args", [["-v", "status"], ["status", "-v"]])
def test_status_command_accepts_verbose_before_or_after_command(
    typer_runner, args: list[str]
) -> None:
    """Verify -v is accepted both as `nd -v status` and `nd status -v`."""
    # Given a fully mocked cluster
    # When invoking the root app with -v before or after the command name
    result = typer_runner.invoke(cli.app, args)

    # Then it exits cleanly
    assert result.exit_code == 0
