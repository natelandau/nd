"""Tests for the nd run command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import nd.commands.run as run_mod
from nd.binary import NomadBinaryError
from nd.cli import app
from nd.commands._orchestration import Outcome, Severity
from nd.jobfiles import JobFile, candidates_for
from nd.nomad.models.deployment import TaskGroupDeploymentState
from tests.builders import deployment, job_stub, register_response, to_payload
from tests.helpers import NOMAD_TEST_ADDR, discard_panel_update, run_with_client

if TYPE_CHECKING:
    from collections.abc import Callable
    from unittest.mock import MagicMock

    import respx

    from nd.binary import NomadBinary
    from nd.jobfiles import JobCandidate
    from tests.conftest import PromptAnswers

_WEB_BODY = (
    b'{"Job": {"ID": "web", "TaskGroups": [{"Name": "app", "Tasks": [{"Name": "server"}]}]}}'
)


def _dead_targets(*names: str) -> list[JobCandidate]:
    """Build run candidates for the given job names (one file each)."""
    files = [JobFile(path=Path(f"/j/{n}.hcl"), job_names=[n]) for n in names]
    return candidates_for(files)


def test_cluster_job_states_splits_running_and_dead(httpx2_mock: respx.Router) -> None:
    """Verify the cluster job list is split into running and dead name sets."""
    # Given a cluster reporting one running and one dead job
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=[to_payload(job_stub("web")), to_payload(job_stub("api", status="dead"))]
    )

    # When fetching the split job states
    running, dead = run_with_client(run_mod._cluster_job_states)

    # Then running and dead are separated by status
    assert running == {"web"}
    assert dead == {"api"}


@pytest.mark.usefixtures("nomad_env")
def test_run_no_candidates_exits_clean(httpx2_mock: respx.Router, typer_runner) -> None:
    """Verify run exits 0 with a message when no deployable files exist."""
    # Given no job directories and no jobs in the cluster
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[])

    # When invoking the run command
    result = typer_runner.invoke(app, ["run"])

    # Then it exits cleanly with code 0
    assert result.exit_code == 0


def test_register_detached_registers_without_watching(
    httpx2_mock: respx.Router, fake_nomad_binary: MagicMock
) -> None:
    """Verify --detach compiles and registers each job but polls no rollout state."""
    # Given a candidate, a binary that compiles to a body, and a register endpoint
    candidate = _dead_targets("web")[0]
    register_route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=to_payload(register_response(job_modify_index=7))
    )
    nomad = fake_nomad_binary
    nomad.compile_job.return_value = _WEB_BODY

    # When registering with detach
    exit_code = run_with_client(
        lambda client: run_mod._register_detached(client, [candidate], nomad)
    )

    # Then it exits 0, registers once, and never queries deployments or allocations
    assert exit_code == 0
    assert register_route.called
    assert not any(
        call.request.url.path.endswith(("/deployments", "/allocations"))
        for call in httpx2_mock.calls
    )


@pytest.mark.usefixtures("nomad_env")
def test_run_app_detach_skips_watch(
    httpx2_mock: respx.Router,
    job_files: Callable[..., Path],
    fake_nomad_binary: MagicMock,
    typer_runner,
) -> None:
    """Verify the run command with --detach registers without entering the watch loop."""
    # Given one deployable file, a stubbed binary, and a register endpoint
    job_files("web.hcl", "web")
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[])
    fake_nomad_binary.compile_job.return_value = _WEB_BODY
    httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=to_payload(register_response()))

    # When invoking run --detach naming the job so it auto-selects
    result = typer_runner.invoke(app, ["run", "web", "--detach"])

    # Then it exits cleanly without polling any rollout state
    assert result.exit_code == 0
    assert not any(
        call.request.url.path.endswith(("/deployments", "/allocations"))
        for call in httpx2_mock.calls
    )


def test_maybe_purge_dead_clean_purges_all(httpx2_mock: respx.Router) -> None:
    """Verify --clean purges every dead target without prompting."""
    # Given a dead target and clean=True
    delete_route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(
        json={"EvalID": "e1"}
    )

    # When purging with clean set
    run_with_client(
        lambda client: run_mod._maybe_purge_dead(client, _dead_targets("web"), clean=True)
    )

    # Then a purging deregister is issued for the dead job
    assert delete_route.called
    assert delete_route.calls.last.request.url.params.get("purge") == "true"


def test_maybe_purge_dead_declined_does_not_purge(
    httpx2_mock: respx.Router, interactive_session: PromptAnswers
) -> None:
    """Verify answering no to the prompt leaves the dead job in place."""
    # Given an interactive session where the user declines
    interactive_session.choice = False
    # Don't register a delete route since we expect no deregister to be issued

    # When purging without clean
    run_with_client(
        lambda client: run_mod._maybe_purge_dead(client, _dead_targets("web"), clean=False)
    )

    # Then no DELETE request is made
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def test_maybe_purge_dead_non_interactive_does_not_prompt(
    httpx2_mock: respx.Router, monkeypatch
) -> None:
    """Verify a non-interactive session runs on top without prompting."""
    # Given no TTY and clean=False
    monkeypatch.setattr(run_mod, "can_prompt", lambda: False)
    # Don't register a delete route since we expect no deregister to be issued

    # When purging without clean
    run_with_client(
        lambda client: run_mod._maybe_purge_dead(client, _dead_targets("web"), clean=False)
    )

    # Then no DELETE request is made and the prompt is skipped
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def test_maybe_purge_dead_continues_after_one_failure(httpx2_mock: respx.Router) -> None:
    """Verify a purge failure on one job does not stop purging the rest."""
    # Given two dead targets where the first purge fails
    fail_route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(500)
    ok_route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/api").respond(json={"EvalID": "e1"})

    # When purging both with clean set
    run_with_client(
        lambda client: run_mod._maybe_purge_dead(client, _dead_targets("web", "api"), clean=True)
    )

    # Then both are attempted despite the first failing
    assert fail_route.called
    assert ok_route.called


@pytest.mark.usefixtures("nomad_env")
def test_run_clean_purges_dead_before_register(
    httpx2_mock: respx.Router,
    job_files: Callable[..., Path],
    fake_nomad_binary: MagicMock,
    typer_runner,
) -> None:
    """Verify --clean purges a dead job before registering the new version."""
    # Given a discovered job "web" that the cluster reports as dead
    job_files("web.hcl", "web")
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=[to_payload(job_stub("web", status="dead"))]
    )
    fake_nomad_binary.compile_job.return_value = _WEB_BODY
    delete_route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(
        json={"EvalID": "e1"}
    )
    register_route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=to_payload(register_response(job_modify_index=5))
    )

    # When running with --clean --detach (detach skips the rollout watch)
    result = typer_runner.invoke(app, ["run", "web", "--clean", "--detach"])

    # Then the purge is issued before the register
    assert result.exit_code == 0
    assert delete_route.called
    assert register_route.called
    ops = [f"{c.request.method} {c.request.url.path}" for c in httpx2_mock.calls]
    assert ops.index("DELETE /v1/job/web") < ops.index("POST /v1/jobs")


@pytest.mark.usefixtures("nomad_env")
@pytest.mark.usefixtures("fake_nomad_binary")
def test_run_clean_dry_run_does_not_purge(
    httpx2_mock: respx.Router, job_files: Callable[..., Path], typer_runner
) -> None:
    """Verify --dry-run reports the purge but never issues the deregister."""
    # Given a discovered dead job and --clean --dry-run
    job_files("web.hcl", "web")
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=[to_payload(job_stub("web", status="dead"))]
    )

    # When running as a dry run
    result = typer_runner.invoke(app, ["run", "web", "--clean", "--dry-run"])

    # Then nothing is purged
    assert result.exit_code == 0
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def _deploy_web(nomad: NomadBinary) -> Outcome:
    """Run the per-job deploy for a single `web` candidate against the mocked cluster."""
    return run_with_client(
        lambda client: run_mod._deploy_one(
            client,
            _dead_targets("web")[0],
            discard_panel_update,
            node_names={},
            nomad=nomad,
        )
    )


def test_deploy_one_registers_compiled_job_and_keeps_warnings(
    httpx2_mock: respx.Router, fake_nomad_binary: MagicMock
) -> None:
    """Verify a deploy registers the compiled body and carries register warnings to the outcome."""
    # Given a job that compiles, registers with a warning, and deploys successfully
    nomad = fake_nomad_binary
    nomad.compile_job.return_value = _WEB_BODY
    register_route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=to_payload(
            register_response(job_modify_index=5, warnings="group app: deprecated field")
        )
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(json=[])
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/deployments").respond(
        json=[
            to_payload(
                deployment(
                    "web",
                    status="successful",
                    create_index=5,
                    task_groups={
                        "app": TaskGroupDeploymentState(desired_total=1, healthy_allocs=1)
                    },
                )
            )
        ]
    )

    # When deploying it
    outcome = _deploy_web(nomad)

    # Then it succeeds, the compiled bytes were sent as is, and the warning is kept
    assert outcome.severity is Severity.OK
    assert register_route.calls.last.request.content == _WEB_BODY
    assert outcome.warnings == "group app: deprecated field"


@pytest.mark.parametrize(
    ("compile_side_effect"),
    [
        pytest.param(NomadBinaryError("bad hcl"), id="compile-fails"),
        pytest.param([b'{"Job": {"TaskGroups": "not-a-list"}}'], id="spec-malformed"),
    ],
)
def test_deploy_one_failure_before_register_reports_failed(
    compile_side_effect: Exception | list[bytes],
    httpx2_mock: respx.Router,
    fake_nomad_binary: MagicMock,
) -> None:
    """Verify a job that fails to compile or parse is reported failed and never registered."""
    # Given a job whose compile step raises or yields a spec of the wrong shape
    nomad = fake_nomad_binary
    nomad.compile_job.side_effect = compile_side_effect
    # No register route is mocked, so any register attempt fails the test as an unmocked call

    # When deploying it
    outcome = _deploy_web(nomad)

    # Then the outcome is a failure and no request reached the cluster
    assert outcome.severity is Severity.FAIL
    assert not httpx2_mock.calls


@pytest.mark.usefixtures("nomad_env")
def test_run_invalid_job_file_exits_without_registering(
    httpx2_mock: respx.Router,
    job_files: Callable[..., Path],
    fake_nomad_binary: MagicMock,
    typer_runner,
) -> None:
    """Verify a job file that fails validation is never registered or purged."""
    # Given a dead job whose local file fails validation
    job_files("web.hcl", "web")
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=[to_payload(job_stub("web", status="dead"))]
    )
    fake_nomad_binary.validate_all.side_effect = NomadBinaryError("web.hcl: invalid")

    # When running it with --clean, which would otherwise purge the dead job first
    result = typer_runner.invoke(app, ["run", "web", "--clean"])

    # Then the command fails before any purge or register is sent
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert not any(call.request.method in ("DELETE", "POST") for call in httpx2_mock.calls)
