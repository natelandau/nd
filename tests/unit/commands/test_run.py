"""Tests for the nd run command."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import httpx  # respx-bundled; used to build sequenced mock responses
from typer.testing import CliRunner

import nd.commands.run as run_mod
from nd.cli import app
from nd.commands.run import deploy_phase
from nd.jobfiles import JobFile, candidates_for
from nd.nomad import NomadClient, NomadConfig

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

    import pytest
    import respx

_ADDR = "http://nomad.test:4646"

# Reusable deployment list stub shape for mocking /v1/job/:id/deployments
_DEPLOY_LIST_STUB = {
    "ID": "d1",
    "JobID": "web",
    "Status": "running",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}

# Reusable allocation stub shape matching AllocListStub required fields
_ALLOC_STUB = {
    "ID": "a1",
    "Name": "batch.batch[0]",
    "Namespace": "default",
    "NodeID": "n1",
    "JobID": "batch",
    "TaskGroup": "batch",
    "ClientStatus": "complete",
    "DesiredStatus": "run",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}


def _async_return(value: object) -> Callable[..., Coroutine[Any, Any, object]]:
    async def _inner(*args: object, **kwargs: object) -> object:
        return value

    return _inner


def test_candidates_for_excludes_running() -> None:
    """Verify already-running job names are filtered out of run candidates."""
    # Given two job files, one whose job is already running
    files = [
        JobFile(path=Path("/j/a.hcl"), job_names=["web", "worker"]),
        JobFile(path=Path("/j/b.hcl"), job_names=["db"]),
    ]

    # When computing candidates excluding running names
    cands = candidates_for(files, exclude_names={"web"})

    # Then only the not-running job names are returned
    assert sorted(c.name for c in cands) == ["db", "worker"]


def test_deploy_phase_reports_health() -> None:
    """Verify the deploy phase summarizes healthy/desired allocations."""

    # Given a fake deployment with two task groups
    class _TG:
        def __init__(self, healthy: int, desired: int) -> None:
            self.healthy_allocs = healthy
            self.desired_total = desired

    class _Dep:
        status = "running"
        task_groups: dict = {"app": _TG(1, 2), "sidecar": _TG(0, 1)}  # noqa: RUF012

    # When computing the deploy phase string
    result = deploy_phase(_Dep())  # type: ignore[arg-type]

    # Then the string summarizes totals across all task groups
    assert result == "running: 1/3 healthy"


def test_task_lifecycle_orders_tasks_and_excludes_poststop() -> None:
    """Verify lifecycle parsing orders prestart, main, sidecar and drops poststop."""
    import msgspec

    from nd.commands.run import task_lifecycle

    # Given a compiled job with prestart, main, poststart-sidecar, and poststop tasks
    body = msgspec.json.encode(
        {
            "Job": {
                "TaskGroups": [
                    {
                        "Name": "cartlog-group",
                        "Tasks": [
                            {"Name": "cartlog", "Lifecycle": None},
                            {
                                "Name": "create_filesystem",
                                "Lifecycle": {"Hook": "prestart", "Sidecar": False},
                            },
                            {
                                "Name": "cartlog_ezbak_sidecar",
                                "Lifecycle": {"Hook": "poststart", "Sidecar": True},
                            },
                            {
                                "Name": "poststop-ezbak",
                                "Lifecycle": {"Hook": "poststop", "Sidecar": False},
                            },
                        ],
                    }
                ]
            }
        }
    )

    # When parsing the compiled spec
    group = task_lifecycle(body)["cartlog-group"]

    # Then poststop is excluded and the rest order prestart < main < sidecar with labels
    assert "poststop-ezbak" not in group
    assert sorted(group, key=lambda n: group[n][0]) == [
        "create_filesystem",
        "cartlog",
        "cartlog_ezbak_sidecar",
    ]
    assert group["create_filesystem"][1] == "prestart"
    assert group["cartlog"][1] == "main"
    assert group["cartlog_ezbak_sidecar"][1] == "sidecar"


def test_run_no_candidates_exits_clean(monkeypatch) -> None:
    """Verify run exits 0 with a message when no deployable files exist."""
    # Given no job directories and no running jobs
    monkeypatch.setattr(run_mod, "load_job_directories", list)
    monkeypatch.setattr(run_mod, "discover_job_files", lambda dirs: [])
    # Avoid a real Nomad call: stub the cluster job listing to empty.
    monkeypatch.setattr(run_mod, "_running_job_names", _async_return(set()))

    # When invoking the run command
    result = CliRunner().invoke(app, ["run"])

    # Then it exits cleanly with code 0
    assert result.exit_code == 0


def test_register_detached_registers_without_watching(httpx2_mock: respx.Router, mocker) -> None:
    """Verify --detach compiles and registers each job but polls no rollout state."""
    # Given a candidate, a binary that compiles to a body, and a register endpoint
    candidate = candidates_for(
        [JobFile(path=Path("/j/web.hcl"), job_names=["web"])], exclude_names=set()
    )[0]
    register_route = httpx2_mock.post(f"{_ADDR}/v1/jobs").respond(
        json={"EvalID": "e1", "JobModifyIndex": 7, "Warnings": ""}
    )
    nomad = mocker.MagicMock()
    nomad.compile_to_json.return_value = b'{"Job": {"ID": "web"}}'

    # When registering with detach
    async def go() -> int:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await run_mod._register_detached(client, [candidate], nomad)

    exit_code = asyncio.run(go())

    # Then it exits 0, registers once, and never queries deployments or allocations
    assert exit_code == 0
    assert register_route.called
    assert not any(
        call.request.url.path.endswith(("/deployments", "/allocations"))
        for call in httpx2_mock.calls
    )


def test_run_app_detach_skips_watch(
    httpx2_mock: respx.Router, monkeypatch, mocker, tmp_path
) -> None:
    """Verify the run command with --detach registers without entering the watch loop."""
    # Given one deployable file, a stubbed binary, and a register endpoint
    monkeypatch.setattr(run_mod, "load_job_directories", list)
    monkeypatch.setattr(
        run_mod,
        "discover_job_files",
        lambda dirs: [JobFile(path=Path("/j/web.hcl"), job_names=["web"])],
    )
    monkeypatch.setattr(run_mod, "_running_job_names", _async_return(set()))
    # Isolate the config so NomadConfig.resolve() targets the mock, not a real ~/.config/nd.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    nomad = mocker.MagicMock()
    nomad.compile_to_json.return_value = b'{"Job": {"ID": "web"}}'
    monkeypatch.setattr(run_mod.NomadBinary, "create", classmethod(lambda cls, cfg: nomad))
    httpx2_mock.post(f"{_ADDR}/v1/jobs").respond(json={"EvalID": "e1", "Warnings": ""})

    # When invoking run --detach naming the job so it auto-selects
    result = CliRunner().invoke(app, ["run", "web", "--detach"])

    # Then it exits cleanly without polling any rollout state
    assert result.exit_code == 0
    assert not any(
        call.request.url.path.endswith(("/deployments", "/allocations"))
        for call in httpx2_mock.calls
    )


def test_watch_service_success_reports_deployed(httpx2_mock: respx.Router) -> None:
    """Verify a service job whose deployment reads back as successful returns DEPLOYED."""
    # Given a job with one running deployment that then resolves to successful
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(json=[_DEPLOY_LIST_STUB])
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])
    httpx2_mock.get(f"{_ADDR}/v1/deployment/d1").respond(
        json={
            "ID": "d1",
            "JobID": "web",
            "Status": "successful",
            "StatusDescription": "Deployment completed successfully",
            "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
        }
    )

    # When watching the deployment to completion
    async def go() -> run_mod.DeployOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await run_mod._watch(
                client, "web", node_names={}, lifecycle={}, update=lambda *_a: None
            )

    outcome = asyncio.run(go())

    # Then the outcome status is DEPLOYED
    assert outcome.status is run_mod.DeployStatus.DEPLOYED
    assert outcome.name == "web"


def test_watch_service_failure_reports_failed(httpx2_mock: respx.Router) -> None:
    """Verify a service job whose deployment reads back as failed returns FAILED with detail."""
    # Given a job with one running deployment that then resolves to failed
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(json=[_DEPLOY_LIST_STUB])
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])
    httpx2_mock.get(f"{_ADDR}/v1/deployment/d1").respond(
        json={
            "ID": "d1",
            "JobID": "web",
            "Status": "failed",
            "StatusDescription": "Rollout timed out",
            "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 0}},
        }
    )

    # When watching the deployment to completion
    async def go() -> run_mod.DeployOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await run_mod._watch(
                client, "web", node_names={}, lifecycle={}, update=lambda *_a: None
            )

    outcome = asyncio.run(go())

    # Then the outcome status is FAILED and carries the status description
    assert outcome.status is run_mod.DeployStatus.FAILED
    assert outcome.detail == "Rollout timed out"


def test_watch_batch_all_allocs_complete_reports_deployed(httpx2_mock: respx.Router) -> None:
    """Verify a batch job with no deployments and all allocs complete returns DEPLOYED."""
    # Given a batch job with no deployments and one allocation in complete status
    httpx2_mock.get(f"{_ADDR}/v1/job/batch/deployments").respond(json=[])
    httpx2_mock.get(f"{_ADDR}/v1/job/batch/allocations").respond(json=[_ALLOC_STUB])

    # When watching the job allocations to completion
    async def go() -> run_mod.DeployOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await run_mod._watch(
                client, "batch", node_names={}, lifecycle={}, update=lambda *_a: None
            )

    outcome = asyncio.run(go())

    # Then the outcome status is DEPLOYED
    assert outcome.status is run_mod.DeployStatus.DEPLOYED
    assert outcome.name == "batch"


def test_watch_skips_transient_alloc_decode_error(httpx2_mock: respx.Router, mocker) -> None:
    """Verify a one-off allocation decode error skips the poll instead of failing the deploy."""
    # Given the first allocations poll returns an undecodable body, then a clean one
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[{"unexpected": "shape"}]),
            httpx.Response(200, json=[]),
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(json=[_DEPLOY_LIST_STUB])
    httpx2_mock.get(f"{_ADDR}/v1/deployment/d1").respond(
        json={
            "ID": "d1",
            "JobID": "web",
            "Status": "successful",
            "StatusDescription": "Deployment completed successfully",
            "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
        }
    )
    # And a no-op sleep so the retry runs instantly
    mocker.patch("nd.commands.run.asyncio.sleep", autospec=True)

    # When watching a job whose first poll cannot decode its allocations
    async def go() -> run_mod.DeployOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await run_mod._watch(
                client, "web", node_names={}, lifecycle={}, update=lambda *_a: None
            )

    outcome = asyncio.run(go())

    # Then the transient error is skipped and the next poll resolves to DEPLOYED
    assert outcome.status is run_mod.DeployStatus.DEPLOYED


def test_watch_ignores_stale_successful_deployment_from_prior_run(
    httpx2_mock: respx.Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a re-run job's watch ignores the prior run's already-successful deployment."""
    # Given zero-duration timeout and poll interval so the test completes instantly
    monkeypatch.setattr(run_mod, "DEPLOY_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(run_mod, "POLL_INTERVAL_SECONDS", 0.0)

    # Given the only deployment present is a stale, already-successful one from the
    # previous run (created at index 1), while this registration happened at index 10
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {
                "ID": "old",
                "JobID": "web",
                "Status": "successful",
                "CreateIndex": 1,
                "ModifyIndex": 2,
            }
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching with the new registration's modify index as the floor
    async def go() -> run_mod.DeployOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await run_mod._watch(
                client,
                "web",
                node_names={},
                lifecycle={},
                update=lambda *_a: None,
                since_index=10,
            )

    outcome = asyncio.run(go())

    # Then the stale deployment does not short-circuit the watch; it keeps waiting
    assert outcome.status is run_mod.DeployStatus.TIMEOUT


def test_watch_follows_fresh_deployment_past_stale_one(httpx2_mock: respx.Router) -> None:
    """Verify the watch selects this run's deployment, not an earlier successful one."""
    # Given a stale successful deployment (index 1) alongside this run's deployment
    # (index 11), returned in an order that puts the stale one first
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {
                "ID": "old",
                "JobID": "web",
                "Status": "successful",
                "CreateIndex": 1,
                "ModifyIndex": 2,
            },
            {
                "ID": "new",
                "JobID": "web",
                "Status": "running",
                "CreateIndex": 11,
                "ModifyIndex": 12,
            },
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])
    httpx2_mock.get(f"{_ADDR}/v1/deployment/new").respond(
        json={
            "ID": "new",
            "JobID": "web",
            "Status": "successful",
            "StatusDescription": "Deployment completed successfully",
            "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
        }
    )

    # When watching with this registration's modify index as the floor
    async def go() -> run_mod.DeployOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await run_mod._watch(
                client,
                "web",
                node_names={},
                lifecycle={},
                update=lambda *_a: None,
                since_index=10,
            )

    outcome = asyncio.run(go())

    # Then it reads this run's deployment (ID "new"), not the stale one, and reports DEPLOYED
    assert outcome.status is run_mod.DeployStatus.DEPLOYED
    assert any(call.request.url.path.endswith("/deployment/new") for call in httpx2_mock.calls)
    assert not any(call.request.url.path.endswith("/deployment/old") for call in httpx2_mock.calls)


def test_watch_times_out_when_never_terminal(
    httpx2_mock: respx.Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify _watch returns TIMEOUT when the deployment never reaches a terminal state."""
    # Given zero-duration timeout and poll interval so the test completes instantly
    monkeypatch.setattr(run_mod, "DEPLOY_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(run_mod, "POLL_INTERVAL_SECONDS", 0.0)

    # Given a deployment that perpetually stays in running state
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(json=[_DEPLOY_LIST_STUB])
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])
    httpx2_mock.get(f"{_ADDR}/v1/deployment/d1").respond(
        json={
            "ID": "d1",
            "JobID": "web",
            "Status": "running",
            "StatusDescription": "",
            "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 0}},
        }
    )

    # When watching a job that never becomes terminal
    async def go() -> run_mod.DeployOutcome:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await run_mod._watch(
                client, "web", node_names={}, lifecycle={}, update=lambda *_a: None
            )

    outcome = asyncio.run(go())

    # Then the outcome is TIMEOUT, not a hang
    assert outcome.status is run_mod.DeployStatus.TIMEOUT
