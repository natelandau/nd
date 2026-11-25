"""Tests for the nd run command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import nd.commands.run as run_mod
from nd.binary import NomadBinary, NomadBinaryError
from nd.cli import app
from nd.commands._orchestration import Outcome, Severity
from nd.jobfiles import JobFile, candidates_for
from nd.nomad.models.deployment import TaskGroupDeploymentState
from tests.builders import deployment, job_stub, to_payload
from tests.helpers import NOMAD_TEST_ADDR, async_return, discard_panel_update, run_with_client

if TYPE_CHECKING:
    import respx

    from nd.jobfiles import JobCandidate


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


def test_run_no_candidates_exits_clean(monkeypatch, typer_runner) -> None:
    """Verify run exits 0 with a message when no deployable files exist."""
    # Given no job directories and no running jobs
    monkeypatch.setattr(run_mod, "load_job_directories", list)
    monkeypatch.setattr(run_mod, "discover_job_files", lambda dirs: [])
    monkeypatch.setattr(run_mod, "_cluster_job_states", async_return((set(), set())))

    # When invoking the run command
    result = typer_runner.invoke(app, ["run"])

    # Then it exits cleanly with code 0
    assert result.exit_code == 0


def test_register_detached_registers_without_watching(httpx2_mock: respx.Router, mocker) -> None:
    """Verify --detach compiles and registers each job but polls no rollout state."""
    # Given a candidate, a binary that compiles to a body, and a register endpoint
    candidate = candidates_for(
        [JobFile(path=Path("/j/web.hcl"), job_names=["web"])], exclude_names=set()
    )[0]
    register_route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json={"EvalID": "e1", "JobModifyIndex": 7, "Warnings": ""}
    )
    nomad = mocker.MagicMock(spec=NomadBinary)
    nomad.compile_job.return_value = b'{"Job": {"ID": "web"}}'

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
    httpx2_mock: respx.Router, monkeypatch, mocker, typer_runner
) -> None:
    """Verify the run command with --detach registers without entering the watch loop."""
    # Given one deployable file, a stubbed binary, and a register endpoint
    monkeypatch.setattr(run_mod, "load_job_directories", list)
    monkeypatch.setattr(
        run_mod,
        "discover_job_files",
        lambda dirs: [JobFile(path=Path("/j/web.hcl"), job_names=["web"])],
    )
    monkeypatch.setattr(run_mod, "_cluster_job_states", async_return((set(), set())))
    nomad = mocker.MagicMock(spec=NomadBinary)
    nomad.compile_job.return_value = b'{"Job": {"ID": "web"}}'
    monkeypatch.setattr(run_mod.NomadBinary, "create", classmethod(lambda cls, cfg: nomad))
    httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json={"EvalID": "e1", "Warnings": ""})

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


def test_maybe_purge_dead_declined_does_not_purge(httpx2_mock: respx.Router, monkeypatch) -> None:
    """Verify answering no to the prompt leaves the dead job in place."""
    # Given an interactive session where the user declines
    monkeypatch.setattr(run_mod, "can_prompt", lambda: True)
    monkeypatch.setattr(run_mod, "confirm_jobs", async_return(False))  # noqa: FBT003
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
    httpx2_mock: respx.Router, monkeypatch, mocker, tmp_path, typer_runner
) -> None:
    """Verify --clean purges a dead job before registering the new version."""
    # Given a discovered job "web" that the cluster reports as dead
    monkeypatch.setattr(run_mod, "load_job_directories", list)
    monkeypatch.setattr(
        run_mod,
        "discover_job_files",
        lambda dirs: [JobFile(path=tmp_path / "web.hcl", job_names=["web"])],
    )
    monkeypatch.setattr(run_mod, "_cluster_job_states", async_return((set(), {"web"})))
    nomad = mocker.MagicMock(spec=NomadBinary)
    nomad.validate_all.return_value = None
    nomad.compile_job.return_value = b'{"Job": {"ID": "web"}}'
    monkeypatch.setattr(run_mod.NomadBinary, "create", classmethod(lambda cls, cfg: nomad))
    delete_route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(
        json={"EvalID": "e1"}
    )
    register_route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json={"EvalID": "e1", "Warnings": "", "JobModifyIndex": 5}
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
def test_run_clean_dry_run_does_not_purge(
    httpx2_mock: respx.Router, monkeypatch, mocker, tmp_path, typer_runner
) -> None:
    """Verify --dry-run reports the purge but never issues the deregister."""
    # Given a discovered dead job and --clean --dry-run
    monkeypatch.setattr(run_mod, "load_job_directories", list)
    monkeypatch.setattr(
        run_mod,
        "discover_job_files",
        lambda dirs: [JobFile(path=tmp_path / "web.hcl", job_names=["web"])],
    )
    monkeypatch.setattr(run_mod, "_cluster_job_states", async_return((set(), {"web"})))
    nomad = mocker.MagicMock(spec=NomadBinary)
    nomad.validate_all.return_value = None
    monkeypatch.setattr(run_mod.NomadBinary, "create", classmethod(lambda cls, cfg: nomad))

    # When running as a dry run
    result = typer_runner.invoke(app, ["run", "web", "--clean", "--dry-run"])

    # Then nothing is purged
    assert result.exit_code == 0
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


_WEB_BODY = (
    b'{"Job": {"ID": "web", "TaskGroups": [{"Name": "app", "Tasks": [{"Name": "server"}]}]}}'
)


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
    httpx2_mock: respx.Router, mocker
) -> None:
    """Verify a deploy registers the compiled body and carries register warnings to the outcome."""
    # Given a job that compiles, registers with a warning, and deploys successfully
    nomad = mocker.MagicMock(spec=NomadBinary)
    nomad.compile_job.return_value = _WEB_BODY
    register_route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json={"EvalID": "e1", "JobModifyIndex": 5, "Warnings": "group app: deprecated field"}
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
    ("compile_result"),
    [
        pytest.param(NomadBinaryError("bad hcl"), id="compile-fails"),
        pytest.param(b'{"Job": {"TaskGroups": "not-a-list"}}', id="spec-malformed"),
    ],
)
def test_deploy_one_failure_before_register_reports_failed(
    compile_result: Exception | bytes, httpx2_mock: respx.Router, mocker
) -> None:
    """Verify a job that fails to compile or parse is reported failed and never registered."""
    # Given a job whose compile step raises or yields a spec of the wrong shape
    nomad = mocker.MagicMock(spec=NomadBinary)
    if isinstance(compile_result, Exception):
        nomad.compile_job.side_effect = compile_result
    else:
        nomad.compile_job.return_value = compile_result
    # No register route is mocked, so any register attempt fails the test as an unmocked call

    # When deploying it
    outcome = _deploy_web(nomad)

    # Then the outcome is a failure and no request reached the cluster
    assert outcome.severity is Severity.FAIL
    assert not httpx2_mock.calls
