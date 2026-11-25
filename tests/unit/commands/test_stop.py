"""Tests for the stop command."""

import pytest
import respx
from nclutils import pp
from rich.console import Console

from nd.commands import stop as stop_module
from nd.commands.stop import _build_dry_run_panel, stopping_title
from tests.builders import job_stub, to_payload
from tests.helpers import NOMAD_TEST_ADDR


@pytest.mark.usefixtures("nomad_env")
def test_stop_app_reports_no_running_jobs(httpx2_mock: respx.Router, typer_runner):
    """Verify the command exits cleanly when no jobs are running."""
    # Given a cluster with only a dead job
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=[to_payload(job_stub("web", status="dead"))]
    )

    # When invoking the stop command
    result = typer_runner.invoke(stop_module.app, [])

    # Then it exits zero with nothing to stop
    assert result.exit_code == 0


@pytest.mark.usefixtures("nomad_env")
def test_stop_app_errors_on_no_substring_match(httpx2_mock: respx.Router, typer_runner):
    """Verify a non-matching job argument exits non-zero."""
    # Given one running job
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("web"))])

    # When invoking with a substring that matches nothing
    result = typer_runner.invoke(stop_module.app, ["zzz"])

    # Then it exits non-zero
    assert result.exit_code == 1


@pytest.mark.usefixtures("nomad_env")
def test_stop_app_no_argument_off_a_terminal_exits_non_zero(
    httpx2_mock: respx.Router, typer_runner
):
    """Verify a scripted stop with no job argument fails instead of silently doing nothing."""
    # Given two running jobs, and no terminal to pick between them
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=[to_payload(job_stub("web")), to_payload(job_stub("api"))]
    )

    # When invoking with no job argument, which would otherwise open a multi-select
    result = typer_runner.invoke(stop_module.app, [])

    # Then it exits non-zero rather than reporting "nothing selected" as success
    assert result.exit_code == 1
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


@pytest.mark.usefixtures("nomad_env")
def test_stop_app_unconfirmable_off_a_terminal_exits_non_zero(
    httpx2_mock: respx.Router, typer_runner
):
    """Verify a scripted stop without --force fails rather than reporting a clean abort."""
    # Given one running job, and no terminal to confirm on
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("web"))])

    # When invoking on an unambiguous job without --force
    result = typer_runner.invoke(stop_module.app, ["web"])

    # Then the unanswerable confirmation is an error, not a silent no-op that exits 0
    assert result.exit_code == 1
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


@pytest.mark.usefixtures("nomad_env")
def test_stop_app_force_stops_single_match(httpx2_mock: respx.Router, mocker, typer_runner):
    """Verify a single substring match with --force stops without prompting."""
    # Given one running job that drains immediately
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("web"))])
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/nodes").respond(json=[])
    httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(json=[])
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When invoking with --force on the substring
    result = typer_runner.invoke(stop_module.app, ["we", "--force"])

    # Then it stops the job and exits cleanly
    assert result.exit_code == 0


@pytest.mark.usefixtures("nomad_env")
def test_stop_app_detach_issues_stop_without_watching(httpx2_mock: respx.Router, typer_runner):
    """Verify --detach issues the stop but never polls allocations to watch the drain."""
    # Given one running job
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("web"))])
    stop_route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})

    # When invoking with --detach (and --force to skip the confirm prompt)
    result = typer_runner.invoke(stop_module.app, ["we", "--force", "--detach"])

    # Then the stop is issued once and no allocations are polled
    assert result.exit_code == 0
    assert stop_route.called
    assert not any(call.request.url.path.endswith("/allocations") for call in httpx2_mock.calls)


@pytest.mark.usefixtures("nomad_env")
def test_stop_app_no_shutdown_delay_passthrough(httpx2_mock: respx.Router, typer_runner):
    """Verify --no-shutdown-delay forwards the bypass flag on the stop call."""
    # Given one running job, stopped with --detach for a short path
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("web"))])
    stop_route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})

    # When invoking with --no-shutdown-delay
    result = typer_runner.invoke(
        stop_module.app, ["we", "--force", "--detach", "--no-shutdown-delay"]
    )

    # Then the deregister carries no_shutdown_delay=true
    assert result.exit_code == 0
    assert stop_route.calls.last.request.url.params["no_shutdown_delay"] == "true"


@pytest.mark.usefixtures("nomad_env")
def test_stop_app_dry_run_skips_delete(httpx2_mock: respx.Router, typer_runner):
    """Verify --dry-run resolves the target but never issues the stop call."""
    # Given one running job, and a stop endpoint
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("web"))])

    # When invoking with --dry-run (and --force to skip the confirm prompt)
    result = typer_runner.invoke(stop_module.app, ["we", "--dry-run", "--force"])

    # Then it exits cleanly and never issues a DELETE (the stop call)
    assert result.exit_code == 0
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def test_stopping_title_includes_purge():
    """Verify stopping_title pluralizes and flags purge."""
    # Given a purge stop of two jobs
    # When building the title
    # Then it pluralizes and notes purge
    assert stopping_title(2, purge=True) == "Stopping 2 jobs (purge)"
    assert stopping_title(1, purge=False) == "Stopping 1 job"


def test_build_dry_run_panel_names_targets():
    """Verify the dry-run panel titles the action and names each target job."""
    # Given two purge targets
    panel = _build_dry_run_panel([job_stub("ladder"), job_stub("linkding")], purge=True)
    console = Console(theme=pp.THEME, record=True, force_terminal=True, width=80)

    # When rendering the panel
    console.print(panel)
    text = console.export_text()

    # Then it reads as a purge dry-run and names both jobs
    assert "Would stop 2 jobs (purge)" in text
    assert "ladder" in text
    assert "linkding" in text
    assert "dry-run" in text
