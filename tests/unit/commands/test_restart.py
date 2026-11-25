"""Tests for the nd restart command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from nd.cli import app
from tests.builders import alloc_stub, job_stub, task_state, to_payload
from tests.helpers import NOMAD_TEST_ADDR

if TYPE_CHECKING:
    import respx

_RESTART_URL = f"{NOMAD_TEST_ADDR}/v1/client/allocation/alloc-1/restart"


def _mock_web_job(httpx2_mock: respx.Router, *, status: str = "running") -> None:
    """Mock one `web` job; when running, its single allocation runs two tasks."""
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=[to_payload(job_stub("web", status=status))]
    )
    if status != "running":
        return
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(
        json=[
            to_payload(
                alloc_stub("alloc-1", task_states={"server": task_state(), "proxy": task_state()})
            )
        ]
    )


@pytest.mark.usefixtures("nomad_env")
@pytest.mark.parametrize(
    ("flags", "body"),
    [
        pytest.param([], {}, id="running-tasks"),
        pytest.param(["--task", "server"], {"TaskName": "server"}, id="one-task"),
        pytest.param(["--all-tasks"], {"AllTasks": True}, id="all-tasks"),
    ],
)
def test_restart_requests_the_chosen_scope_unattended(
    httpx2_mock: respx.Router, typer_runner, flags, body
):
    """Verify each scope restarts the resolved allocation with no prompt for a task."""
    # Given a job whose one allocation runs two tasks, in a session that cannot prompt
    _mock_web_job(httpx2_mock)
    route = httpx2_mock.post(_RESTART_URL).respond(json={})

    # When restarting it by name with the scope's flags
    result = typer_runner.invoke(app, ["restart", "web", *flags])

    # Then it exits zero having asked Nomad for exactly that scope
    assert result.exit_code == 0
    assert json.loads(route.calls.last.request.content) == body


@pytest.mark.usefixtures("nomad_env")
def test_restart_rejects_a_task_with_all_tasks(httpx2_mock: respx.Router, typer_runner):
    """Verify combining --task and --all-tasks is a usage error before any request."""
    # Given a configured cluster address
    # When asking for one task and every task at once
    result = typer_runner.invoke(app, ["restart", "web", "--task", "server", "--all-tasks"])

    # Then it is a usage error and Nomad was never contacted
    assert result.exit_code == 2
    assert not httpx2_mock.calls


@pytest.mark.usefixtures("nomad_env")
@pytest.mark.parametrize(
    ("job_status", "flags"),
    [
        pytest.param("running", ["--task", "nope"], id="unknown-task"),
        pytest.param("dead", [], id="job-not-running"),
    ],
)
def test_restart_unresolvable_target_exits_one(
    httpx2_mock: respx.Router, typer_runner, job_status, flags
):
    """Verify a named target that is not running fails without restarting anything."""
    # Given a web job in the given state
    _mock_web_job(httpx2_mock, status=job_status)

    # When restarting a target that cannot resolve
    result = typer_runner.invoke(app, ["restart", "web", *flags])

    # Then it exits 1 and never posts a restart
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert not [c for c in httpx2_mock.calls if c.request.method == "POST"]


@pytest.mark.usefixtures("nomad_env")
def test_restart_dry_run_resolves_but_restarts_nothing(httpx2_mock: respx.Router, typer_runner):
    """Verify --dry-run resolves the allocation, then reports it without restarting it."""
    # Given a running web job
    _mock_web_job(httpx2_mock)

    # When restarting with --dry-run
    result = typer_runner.invoke(app, ["restart", "web", "--dry-run"])

    # Then it exits zero and posts nothing
    assert result.exit_code == 0
    assert not [c for c in httpx2_mock.calls if c.request.method == "POST"]
