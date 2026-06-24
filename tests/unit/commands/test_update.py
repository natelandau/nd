"""Tests for the nd update command."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

import nd.commands.update as update_mod
from nd.binary import NomadBinaryError
from nd.cli import app
from nd.commands.stop import StopOutcome, StopStatus
from nd.commands.update import UpdateOutcome, UpdateStatus, UpdateTarget, build_update_targets
from nd.jobfiles import JobFile
from nd.nomad import NomadClient, NomadConfig, NomadError
from nd.nomad.models.job import JobListStub

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

    import respx

_ADDR = "http://nomad.test:4646"


def _async_return(value: object) -> Callable[..., Coroutine[Any, Any, object]]:
    async def _inner(*args: object, **kwargs: object) -> object:
        return value

    return _inner


def _running(name: str) -> JobListStub:
    return JobListStub(
        id=name,
        name=name,
        type="service",
        status="running",
        priority=50,
        create_index=100,
        modify_index=100,
    )


def test_build_update_targets_intersects_running_and_local() -> None:
    """Verify only running jobs that also have a local file become update targets."""
    # Given two files (web declares web+api, db declares db) and running web+ghost
    files = [
        JobFile(path=Path("/j/web.hcl"), job_names=["web", "api"]),
        JobFile(path=Path("/j/db.hcl"), job_names=["db"]),
    ]
    running = [_running("web"), _running("ghost")]

    # When building update targets
    targets: list[UpdateTarget] = build_update_targets(files, running)

    # Then only "web" qualifies: api is not running, db is not running, ghost has no file
    assert [t.name for t in targets] == ["web"]
    assert targets[0].file.path == Path("/j/web.hcl")
    assert targets[0].job.id == "web"


def _web_target() -> UpdateTarget:
    return UpdateTarget(
        name="web",
        file=JobFile(path=Path("/j/web.hcl"), job_names=["web"]),
        job=_running("web"),
    )


def test_update_one_compile_failure_skips_stop(httpx2_mock: respx.Router, mocker) -> None:
    """Verify a compile failure fails the update and never stops the running job."""
    # Given a binary whose compile raises before anything is torn down
    target = _web_target()
    nomad = mocker.MagicMock()
    nomad.compile_to_json.side_effect = NomadBinaryError("bad hcl")

    # When updating that target
    async def go() -> UpdateOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await update_mod._update_one(
                client, target, node_names={}, update=lambda *_a: None, nomad=nomad, purge=True
            )

    outcome = asyncio.run(go())

    # Then it fails with a compile message and issues no stop (no DELETE)
    assert outcome.status is UpdateStatus.FAILED
    assert "compile failed" in outcome.detail
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def test_update_one_aborts_register_when_stop_fails(
    httpx2_mock: respx.Router, monkeypatch, mocker
) -> None:
    """Verify a failed drain aborts the update before re-registering."""
    # Given a good compile but a stop that fails to drain
    target = _web_target()
    nomad = mocker.MagicMock()
    nomad.compile_to_json.return_value = b'{"Job": {"ID": "web"}}'
    monkeypatch.setattr(
        update_mod,
        "stop_and_wait",
        _async_return(StopOutcome(target.job, StopStatus.FAILED, "boom")),
    )

    # When updating that target
    async def go() -> UpdateOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await update_mod._update_one(
                client, target, node_names={}, update=lambda *_a: None, nomad=nomad, purge=True
            )

    outcome = asyncio.run(go())

    # Then it fails without re-registering
    assert outcome.status is UpdateStatus.FAILED
    assert not any(call.request.method == "POST" for call in httpx2_mock.calls)


def test_update_one_register_failure_reports_job_down(
    httpx2_mock: respx.Router, monkeypatch, mocker
) -> None:
    """Verify a re-register failure after a clean stop reports the job is down."""
    # Given a clean stop but a register that errors
    target = _web_target()
    nomad = mocker.MagicMock()
    nomad.compile_to_json.return_value = b'{"Job": {"ID": "web"}}'
    monkeypatch.setattr(
        update_mod, "stop_and_wait", _async_return(StopOutcome(target.job, StopStatus.STOPPED))
    )
    httpx2_mock.post(f"{_ADDR}/v1/jobs").respond(status_code=500, text="nope")

    # When updating that target
    async def go() -> UpdateOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await update_mod._update_one(
                client, target, node_names={}, update=lambda *_a: None, nomad=nomad, purge=True
            )

    outcome = asyncio.run(go())

    # Then it fails with the "stopped but re-deploy failed" message
    assert outcome.status is UpdateStatus.FAILED
    assert "stopped but re-deploy failed" in outcome.detail


def test_update_one_recreate_sequence_succeeds(httpx2_mock: respx.Router, mocker) -> None:
    """Verify the full stop -> purge -> register -> watch sequence yields UPDATED."""
    # Given a target whose drain is immediate ([] allocs) and whose deployment succeeds
    target = _web_target()
    nomad = mocker.MagicMock()
    nomad.compile_to_json.return_value = b'{"Job": {"ID": "web"}}'
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])
    register_route = httpx2_mock.post(f"{_ADDR}/v1/jobs").respond(
        json={"EvalID": "e2", "JobModifyIndex": 5, "Warnings": ""}
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {"ID": "d1", "JobID": "web", "Status": "running", "CreateIndex": 10, "ModifyIndex": 11}
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/deployment/d1").respond(
        json={
            "ID": "d1",
            "JobID": "web",
            "Status": "successful",
            "StatusDescription": "ok",
            "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
        }
    )

    # When updating with purge enabled
    async def go() -> UpdateOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await update_mod._update_one(
                client, target, node_names={}, update=lambda *_a: None, nomad=nomad, purge=True
            )

    outcome = asyncio.run(go())

    # Then it succeeds, re-registers, and issues a purging DELETE (purge=true)
    assert outcome.status is UpdateStatus.UPDATED
    assert register_route.called
    assert any(
        call.request.url.params.get("purge") == "true"
        for call in httpx2_mock.calls
        if call.request.method == "DELETE"
    )


def test_update_one_no_purge_skips_purge(httpx2_mock: respx.Router, mocker) -> None:
    """Verify --no-purge stops the job but issues no purging DELETE."""
    # Given the same successful sequence but purge disabled
    target = _web_target()
    nomad = mocker.MagicMock()
    nomad.compile_to_json.return_value = b'{"Job": {"ID": "web"}}'
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])
    httpx2_mock.post(f"{_ADDR}/v1/jobs").respond(
        json={"EvalID": "e2", "JobModifyIndex": 5, "Warnings": ""}
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {"ID": "d1", "JobID": "web", "Status": "running", "CreateIndex": 10, "ModifyIndex": 11}
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/deployment/d1").respond(
        json={
            "ID": "d1",
            "JobID": "web",
            "Status": "successful",
            "StatusDescription": "ok",
            "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
        }
    )

    # When updating with purge disabled
    async def go() -> UpdateOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await update_mod._update_one(
                client, target, node_names={}, update=lambda *_a: None, nomad=nomad, purge=False
            )

    outcome = asyncio.run(go())

    # Then it succeeds and never issues a purge=true DELETE
    assert outcome.status is UpdateStatus.UPDATED
    assert not any(
        call.request.url.params.get("purge") == "true"
        for call in httpx2_mock.calls
        if call.request.method == "DELETE"
    )


def test_update_one_watch_error_does_not_escape(
    httpx2_mock: respx.Router, monkeypatch, mocker
) -> None:
    """Verify a Nomad error during the rollout watch becomes FAILED instead of raising."""
    # Given a clean stop, a successful re-register, but a watch that errors mid-poll
    target = _web_target()
    nomad = mocker.MagicMock()
    nomad.compile_to_json.return_value = b'{"Job": {"ID": "web"}}'
    monkeypatch.setattr(
        update_mod, "stop_and_wait", _async_return(StopOutcome(target.job, StopStatus.STOPPED))
    )
    httpx2_mock.post(f"{_ADDR}/v1/jobs").respond(
        json={"EvalID": "e2", "JobModifyIndex": 5, "Warnings": ""}
    )

    async def _raise(*_args: object, **_kwargs: object) -> object:
        msg = "connection reset during poll"
        raise NomadError(msg)

    monkeypatch.setattr(update_mod, "watch_deploy", _raise)

    # When updating that target
    async def go() -> UpdateOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await update_mod._update_one(
                client, target, node_names={}, update=lambda *_a: None, nomad=nomad, purge=True
            )

    outcome = asyncio.run(go())

    # Then the error is contained as a FAILED outcome, not propagated to the panel
    assert outcome.status is UpdateStatus.FAILED
    assert "watch failed" in outcome.detail


def test_update_one_purge_failed_still_redeploys(
    httpx2_mock: respx.Router, monkeypatch, mocker
) -> None:
    """Verify a stop whose purge failed still re-registers, since the workload is down."""
    # Given a clean drain whose garbage-collection failed (workload stopped regardless)
    target = _web_target()
    nomad = mocker.MagicMock()
    nomad.compile_to_json.return_value = b'{"Job": {"ID": "web"}}'
    monkeypatch.setattr(
        update_mod,
        "stop_and_wait",
        _async_return(StopOutcome(target.job, StopStatus.PURGE_FAILED, "purge failed")),
    )
    register_route = httpx2_mock.post(f"{_ADDR}/v1/jobs").respond(
        json={"EvalID": "e2", "JobModifyIndex": 5, "Warnings": ""}
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {"ID": "d1", "JobID": "web", "Status": "running", "CreateIndex": 10, "ModifyIndex": 11}
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])
    httpx2_mock.get(f"{_ADDR}/v1/deployment/d1").respond(
        json={
            "ID": "d1",
            "JobID": "web",
            "Status": "successful",
            "StatusDescription": "ok",
            "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
        }
    )

    # When updating that target
    async def go() -> UpdateOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await update_mod._update_one(
                client, target, node_names={}, update=lambda *_a: None, nomad=nomad, purge=True
            )

    outcome = asyncio.run(go())

    # Then it re-registers and reports UPDATED
    assert outcome.status is UpdateStatus.UPDATED
    assert register_route.called


def test_update_one_drain_timeout_maps_to_timeout(
    httpx2_mock: respx.Router, monkeypatch, mocker
) -> None:
    """Verify a drain that times out yields TIMEOUT and never re-registers."""
    # Given a good compile but a stop that never reaches a terminal drain
    target = _web_target()
    nomad = mocker.MagicMock()
    nomad.compile_to_json.return_value = b'{"Job": {"ID": "web"}}'
    monkeypatch.setattr(
        update_mod,
        "stop_and_wait",
        _async_return(StopOutcome(target.job, StopStatus.TIMEOUT, "still draining")),
    )

    # When updating that target
    async def go() -> UpdateOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await update_mod._update_one(
                client, target, node_names={}, update=lambda *_a: None, nomad=nomad, purge=True
            )

    outcome = asyncio.run(go())

    # Then the outcome is TIMEOUT and no re-register was issued
    assert outcome.status is UpdateStatus.TIMEOUT
    assert not any(call.request.method == "POST" for call in httpx2_mock.calls)


def test_update_no_candidates_exits_clean(monkeypatch, httpx2_mock: respx.Router, tmp_path) -> None:
    """Verify update exits 0 with a message when no running job has a local file."""
    # Given no local files and an empty cluster job list
    monkeypatch.setattr(update_mod, "load_job_directories", list)
    monkeypatch.setattr(update_mod, "discover_job_files", lambda dirs: [])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[])

    # When invoking update
    result = CliRunner().invoke(app, ["update"])

    # Then it exits cleanly
    assert result.exit_code == 0


def test_update_dry_run_reports_without_acting(
    monkeypatch, mocker, httpx2_mock: respx.Router, tmp_path
) -> None:
    """Verify --dry-run validates and reports but stops or registers nothing."""
    # Given one local file whose job is running, and a stubbed binary
    monkeypatch.setattr(update_mod, "load_job_directories", list)
    monkeypatch.setattr(
        update_mod,
        "discover_job_files",
        lambda dirs: [JobFile(path=Path("/j/web.hcl"), job_names=["web"])],
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(
        json=[
            {
                "ID": "web",
                "Name": "web",
                "Type": "service",
                "Status": "running",
                "Priority": 50,
                "CreateIndex": 1,
                "ModifyIndex": 2,
            }
        ]
    )
    nomad = mocker.MagicMock()
    monkeypatch.setattr(update_mod.NomadBinary, "create", classmethod(lambda cls, cfg: nomad))

    # When invoking update --force --dry-run naming the job
    result = CliRunner().invoke(app, ["update", "web", "--force", "--dry-run"])

    # Then it exits 0, validates the file, and issues no stop or register
    assert result.exit_code == 0
    nomad.validate.assert_called_once()
    assert not any(call.request.method in ("DELETE", "POST") for call in httpx2_mock.calls)


def test_update_confirm_decline_aborts(monkeypatch, httpx2_mock: respx.Router, tmp_path) -> None:
    """Verify declining the confirmation prompt aborts without stopping anything."""
    # Given a running job with a local file, but the user declines the prompt
    monkeypatch.setattr(update_mod, "load_job_directories", list)
    monkeypatch.setattr(
        update_mod,
        "discover_job_files",
        lambda dirs: [JobFile(path=Path("/j/web.hcl"), job_names=["web"])],
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(
        json=[
            {
                "ID": "web",
                "Name": "web",
                "Type": "service",
                "Status": "running",
                "Priority": 50,
                "CreateIndex": 1,
                "ModifyIndex": 2,
            }
        ]
    )
    declined: bool = False
    monkeypatch.setattr(update_mod, "select_one", _async_return(declined))

    # When invoking update naming the job (no --force, so it prompts)
    result = CliRunner().invoke(app, ["update", "web"])

    # Then it exits 0 and never stops or registers
    assert result.exit_code == 0
    assert not any(call.request.method in ("DELETE", "POST") for call in httpx2_mock.calls)
