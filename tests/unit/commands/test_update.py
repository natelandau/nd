"""Tests for the nd update command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import nd.commands.update as update_mod
from nd.binary import NomadBinaryError
from nd.cli import app
from nd.commands._lifecycle import StopOutcome
from nd.commands._orchestration import Outcome, Severity
from nd.commands.update import UpdateTarget, build_update_targets
from nd.jobfiles import JobFile
from nd.nomad import NomadError
from nd.nomad.models.deployment import TaskGroupDeploymentState
from tests.builders import deployment, job_stub, register_response, to_payload
from tests.helpers import NOMAD_TEST_ADDR, async_return, discard_panel_update, run_with_client

if TYPE_CHECKING:
    from collections.abc import Callable
    from unittest.mock import MagicMock

    import respx

    from nd.binary import NomadBinary
    from nd.ui.live_panel import PanelUpdate
    from tests.conftest import PromptAnswers

_WEB_BODY = b'{"Job": {"ID": "web"}}'


# Severity, row label, and whether the workload came down, per kind of stop result.
_STOP_KINDS: dict[str, tuple[Severity, str, bool]] = {
    "stopped": (Severity.OK, "stopped", True),
    "purge_failed": (Severity.WARN, "stopped, purge failed", True),
    "timeout": (Severity.WARN, "still draining", False),
    "failed": (Severity.FAIL, "failed", False),
}


def _stop_outcome(kind: str, *, detail: str = "", drained: int = 0) -> StopOutcome:
    """Build the `web` job's stop result of the given kind."""
    severity, label, workload_stopped = _STOP_KINDS[kind]
    return StopOutcome(
        name="web",
        severity=severity,
        label=label,
        detail=detail,
        workload_stopped=workload_stopped,
        drained=drained,
    )


def _web_target() -> UpdateTarget:
    """Build an update target for the running `web` job and its local file."""
    return UpdateTarget(
        name="web",
        file=JobFile(path=Path("/j/web.hcl"), job_names=["web"]),
        job=job_stub("web"),
    )


@pytest.fixture
def compiling_binary(fake_nomad_binary: MagicMock) -> MagicMock:
    """Make the stand-in `nomad` binary's compile step succeed.

    Returns:
        MagicMock: The binary, compiling every job to the `web` body.
    """
    fake_nomad_binary.compile_job.return_value = _WEB_BODY
    return fake_nomad_binary


def _mock_successful_redeploy(httpx2_mock: respx.Router) -> respx.Route:
    """Mock a register and a rollout for `web` that succeed.

    Returns:
        respx.Route: The register route.
    """
    register_route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=to_payload(register_response(eval_id="e2", job_modify_index=5))
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/deployments").respond(
        json=[
            to_payload(
                deployment(
                    "web",
                    status="successful",
                    status_description="ok",
                    create_index=10,
                    task_groups={
                        "app": TaskGroupDeploymentState(desired_total=1, healthy_allocs=1)
                    },
                )
            )
        ]
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(json=[])
    return register_route


def _update_web(
    nomad: NomadBinary, *, purge: bool = True, update: PanelUpdate = discard_panel_update
) -> Outcome:
    """Run the per-job update for the `web` target against the mocked cluster."""
    return run_with_client(
        lambda client: update_mod._update_one(
            client, _web_target(), node_names={}, update=update, nomad=nomad, purge=purge
        )
    )


def test_build_update_targets_intersects_running_and_local() -> None:
    """Verify only running jobs that also have a local file become update targets."""
    # Given two files (web declares web+api, db declares db) and running web+ghost
    files = [
        JobFile(path=Path("/j/web.hcl"), job_names=["web", "api"]),
        JobFile(path=Path("/j/db.hcl"), job_names=["db"]),
    ]
    running = [job_stub("web"), job_stub("ghost")]

    # When building update targets
    targets: list[UpdateTarget] = build_update_targets(files, running)

    # Then only "web" qualifies: api is not running, db is not running, ghost has no file
    assert [t.name for t in targets] == ["web"]
    assert targets[0].file.path == Path("/j/web.hcl")
    assert targets[0].job.id == "web"


@pytest.mark.parametrize(
    "compile_side_effect",
    [
        pytest.param(NomadBinaryError("bad hcl"), id="binary-error"),
        pytest.param([b'{"Job": {"TaskGroups": [{"Tasks": []}]}}'], id="undecodable-spec"),
    ],
)
def test_update_one_compile_failure_skips_stop(
    httpx2_mock: respx.Router,
    fake_nomad_binary: MagicMock,
    compile_side_effect: Exception | list[bytes],
) -> None:
    """Verify a compile or spec-parse failure fails the update and never stops the job."""
    # Given a binary whose compile raises, or emits a spec that does not decode
    fake_nomad_binary.compile_job.side_effect = compile_side_effect

    # When updating that target
    outcome = _update_web(fake_nomad_binary)

    # Then it fails with a compile message and issues no stop (no DELETE)
    assert outcome.severity is Severity.FAIL
    assert "compile failed" in outcome.detail
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def test_update_one_aborts_register_when_stop_fails(
    httpx2_mock: respx.Router, monkeypatch, compiling_binary: MagicMock
) -> None:
    """Verify a failed drain aborts the update before re-registering."""
    # Given a good compile but a stop that fails to drain
    monkeypatch.setattr(
        update_mod, "stop_and_wait", async_return(_stop_outcome("failed", detail="boom"))
    )

    # When updating that target
    outcome = _update_web(compiling_binary)

    # Then it fails without re-registering
    assert outcome.severity is Severity.FAIL
    assert not any(call.request.method == "POST" for call in httpx2_mock.calls)


def test_update_one_register_failure_reports_job_down(
    httpx2_mock: respx.Router, monkeypatch, compiling_binary: MagicMock
) -> None:
    """Verify a re-register failure after a clean stop reports the job is down."""
    # Given a clean stop but a register that errors
    monkeypatch.setattr(update_mod, "stop_and_wait", async_return(_stop_outcome("stopped")))
    httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(status_code=500, text="nope")

    # When updating that target
    outcome = _update_web(compiling_binary)

    # Then it fails with the "stopped but re-deploy failed" message
    assert outcome.severity is Severity.FAIL
    assert "stopped but re-deploy failed" in outcome.detail


@pytest.mark.parametrize(
    "purge",
    [pytest.param(True, id="purge"), pytest.param(False, id="no-purge")],
)
def test_update_one_recreate_sequence_succeeds(
    httpx2_mock: respx.Router, compiling_binary: MagicMock, *, purge: bool
) -> None:
    """Verify stop -> register -> watch yields UPDATED, purging the old job only when asked."""
    # Given a target whose drain is immediate ([] allocs) and whose deployment succeeds
    httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    register_route = _mock_successful_redeploy(httpx2_mock)

    # When updating with purge enabled or disabled
    outcome = _update_web(compiling_binary, purge=purge)

    # Then it succeeds, re-registers, and issues a purging DELETE (purge=true) only with purge
    assert outcome.severity is Severity.OK
    assert register_route.called
    purged = any(
        call.request.url.params.get("purge") == "true"
        for call in httpx2_mock.calls
        if call.request.method == "DELETE"
    )
    assert purged is purge


def test_update_one_watch_error_does_not_escape(
    httpx2_mock: respx.Router, monkeypatch, compiling_binary: MagicMock
) -> None:
    """Verify a Nomad error during the rollout watch becomes FAILED instead of raising."""
    # Given a clean stop, a successful re-register, but a watch that errors mid-poll
    monkeypatch.setattr(update_mod, "stop_and_wait", async_return(_stop_outcome("stopped")))
    httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=to_payload(register_response(eval_id="e2", job_modify_index=5))
    )

    async def _raise(*_args: object, **_kwargs: object) -> object:
        msg = "connection reset during poll"
        raise NomadError(msg)

    monkeypatch.setattr(update_mod, "watch_deploy", _raise)

    # When updating that target
    outcome = _update_web(compiling_binary)

    # Then the error is contained as a FAILED outcome, not propagated to the panel
    assert outcome.severity is Severity.FAIL
    assert "watch failed" in outcome.detail


def test_update_one_purge_failed_still_redeploys(
    httpx2_mock: respx.Router, monkeypatch, compiling_binary: MagicMock
) -> None:
    """Verify a stop whose purge failed still re-registers, since the workload is down."""
    # Given a clean drain whose garbage-collection failed (workload stopped regardless)
    monkeypatch.setattr(
        update_mod,
        "stop_and_wait",
        async_return(_stop_outcome("purge_failed", detail="purge failed")),
    )
    register_route = _mock_successful_redeploy(httpx2_mock)

    # When updating that target
    outcome = _update_web(compiling_binary)

    # Then it re-registers and reports UPDATED
    assert outcome.severity is Severity.OK
    assert register_route.called


def test_update_one_drain_timeout_maps_to_timeout(
    httpx2_mock: respx.Router, monkeypatch, compiling_binary: MagicMock
) -> None:
    """Verify a drain that times out yields TIMEOUT and never re-registers."""
    # Given a good compile but a stop that never reaches a terminal drain
    monkeypatch.setattr(
        update_mod,
        "stop_and_wait",
        async_return(_stop_outcome("timeout", detail="still draining")),
    )

    # When updating that target
    outcome = _update_web(compiling_binary)

    # Then the outcome is TIMEOUT and no re-register was issued
    assert outcome.severity is Severity.WARN
    assert not any(call.request.method == "POST" for call in httpx2_mock.calls)


def test_update_one_marks_previous_version_stopped(
    httpx2_mock: respx.Router, monkeypatch, compiling_binary: MagicMock
) -> None:
    """Verify the deploy phase keeps a persistent 'stopped previous version' marker row."""
    # Given a clean stop that drained two allocations, then a successful re-deploy
    monkeypatch.setattr(
        update_mod, "stop_and_wait", async_return(_stop_outcome("stopped", drained=2))
    )
    _mock_successful_redeploy(httpx2_mock)

    # Capture the first child cell of every update that carries detail rows
    lead_cells: list[str] = []

    def _update(phase: str, children=()) -> None:
        if children:
            lead_cells.append(children[0].cells[0])

    # When updating that target
    outcome = _update_web(compiling_binary, update=_update)

    # Then the deploy phase leads every detail block with a durable stopped marker
    assert outcome.severity is Severity.OK
    assert lead_cells, "expected at least one update carrying detail rows after the stop"
    assert set(lead_cells) == {lead_cells[0]}
    assert "2" in lead_cells[0]


def test_update_one_no_marker_when_stop_times_out(
    httpx2_mock: respx.Router, monkeypatch, compiling_binary: MagicMock
) -> None:
    """Verify a stop that never drained shows no 'stopped previous version' marker."""
    # Given a good compile but a stop that times out (nothing cleanly stopped)
    monkeypatch.setattr(
        update_mod,
        "stop_and_wait",
        async_return(_stop_outcome("timeout", detail="still draining", drained=0)),
    )
    marker_cells: list[str] = []

    def _update(phase: str, children=()) -> None:
        marker_cells.extend(
            c.cells[0] for c in children if "stopped previous version" in c.cells[0]
        )

    # When updating that target
    outcome = _update_web(compiling_binary, update=_update)

    # Then no marker is shown, because the early return skips the re-deploy entirely
    assert outcome.severity is Severity.WARN
    assert not marker_cells


def test_update_one_no_marker_when_nothing_was_running(
    httpx2_mock: respx.Router, monkeypatch, compiling_binary: MagicMock
) -> None:
    """Verify a stop that drained zero allocations shows no marker but still re-deploys."""
    # Given a clean stop that drained nothing (drained == 0), then a successful re-deploy
    monkeypatch.setattr(
        update_mod, "stop_and_wait", async_return(_stop_outcome("stopped", drained=0))
    )
    _mock_successful_redeploy(httpx2_mock)
    marker_cells: list[str] = []

    def _update(phase: str, children=()) -> None:
        marker_cells.extend(
            c.cells[0] for c in children if "stopped previous version" in c.cells[0]
        )

    # When updating that target
    outcome = _update_web(compiling_binary, update=_update)

    # Then it re-deploys cleanly but shows no marker (there was nothing to report drained)
    assert outcome.severity is Severity.OK
    assert not marker_cells


@pytest.mark.usefixtures("nomad_env")
def test_update_no_candidates_exits_clean(httpx2_mock: respx.Router, typer_runner) -> None:
    """Verify update exits 0 with a message when no running job has a local file."""
    # Given no local files and an empty cluster job list
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[])

    # When invoking update
    result = typer_runner.invoke(app, ["update"])

    # Then it exits cleanly
    assert result.exit_code == 0


@pytest.mark.usefixtures("nomad_env")
def test_update_dry_run_reports_without_acting(
    job_files: Callable[..., Path],
    fake_nomad_binary: MagicMock,
    httpx2_mock: respx.Router,
    typer_runner,
) -> None:
    """Verify --dry-run validates and reports but stops or registers nothing."""
    # Given one local file whose job is running, and a stubbed binary
    job_files("web.hcl", "web")
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("web"))])
    nomad = fake_nomad_binary

    # When invoking update --force --dry-run naming the job
    result = typer_runner.invoke(app, ["update", "web", "--force", "--dry-run"])

    # Then it exits 0, validates the file, and issues no stop or register
    assert result.exit_code == 0
    nomad.validate_all.assert_called_once()
    assert not any(call.request.method in ("DELETE", "POST") for call in httpx2_mock.calls)


@pytest.mark.usefixtures("nomad_env")
def test_update_confirm_decline_aborts(
    job_files: Callable[..., Path],
    interactive_session: PromptAnswers,
    httpx2_mock: respx.Router,
    typer_runner,
) -> None:
    """Verify declining the confirmation prompt aborts without stopping anything."""
    # Given a running job with a local file, but the user declines the prompt
    job_files("web.hcl", "web")
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("web"))])
    interactive_session.choice = False

    # When invoking update naming the job (no --force, so it prompts)
    result = typer_runner.invoke(app, ["update", "web"])

    # Then it exits 0 and never stops or registers
    assert result.exit_code == 0
    assert not any(call.request.method in ("DELETE", "POST") for call in httpx2_mock.calls)
