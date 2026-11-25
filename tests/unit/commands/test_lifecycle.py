"""Tests for watching a job deploy or drain to a terminal state."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx  # respx-bundled; used to build sequenced mock responses
import msgspec
import pytest

import nd.commands._lifecycle as lifecycle_mod
from nd.commands._lifecycle import (
    StopOutcome,
    deploy_phase,
    phase_text,
    running_task_names,
    stop_and_wait,
    task_lifecycle,
    watch_deploy,
)
from nd.commands._orchestration import Outcome, Severity
from nd.nomad import NomadClient, NomadConfig, NomadDecodeError
from nd.nomad.models.allocation import AllocListStub
from nd.nomad.models.deployment import Deployment, TaskGroupDeploymentState
from nd.nomad.models.job import JobListStub
from tests.unit.commands.panel_helpers import discard_panel_update

if TYPE_CHECKING:
    import respx

_ADDR = "http://nomad.test:4646"

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


def _job(name: str, status: str = "running") -> JobListStub:
    return msgspec.convert(
        {
            "ID": name,
            "Name": name,
            "Type": "service",
            "Status": status,
            "Priority": 50,
            "CreateIndex": 1,
            "ModifyIndex": 2,
        },
        type=JobListStub,
    )


def _alloc_json(client_status: str) -> dict:
    return {
        "ID": "a",
        "Name": "n",
        "NodeID": "x",
        "JobID": "web",
        "TaskGroup": "web",
        "ClientStatus": client_status,
        "DesiredStatus": "stop",
        "CreateIndex": 1,
        "ModifyIndex": 2,
    }


def _alloc_with_tasks(client_status: str, task_states: dict[str, str]) -> AllocListStub:
    return msgspec.convert(
        {
            **_alloc_json(client_status),
            "TaskStates": {
                name: {"State": state, "Failed": False, "Restarts": 0}
                for name, state in task_states.items()
            },
        },
        type=AllocListStub,
    )


def test_deploy_phase_reports_health() -> None:
    """Verify the deploy phase summarizes healthy/desired allocations."""
    # Given a deployment with two task groups
    deployment = Deployment(
        id="d1",
        job_id="web",
        status="running",
        create_index=1,
        modify_index=2,
        task_groups={
            "app": TaskGroupDeploymentState(healthy_allocs=1, desired_total=2),
            "sidecar": TaskGroupDeploymentState(healthy_allocs=0, desired_total=1),
        },
    )

    # When computing the deploy phase string
    result = deploy_phase(deployment)

    # Then the string summarizes totals across all task groups
    assert result == "running: 1/3 healthy"


def test_task_lifecycle_orders_tasks_and_excludes_poststop() -> None:
    """Verify lifecycle parsing orders prestart, main, sidecar and drops poststop."""
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


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"Job": {"TaskGroups": [{"Tasks": []}]}}',
        b'{"Job": {"TaskGroups": [{"Name": "g", "Tasks": [{"Lifecycle": null}]}]}}',
    ],
    ids=["malformed", "group-without-name", "task-without-name"],
)
def test_task_lifecycle_rejects_unexpected_shape(body: bytes) -> None:
    """Verify a compiled spec of the wrong shape raises NomadDecodeError."""
    # Given a compiled job body that is not a valid job spec
    # When / Then parsing it raises the client's decode error
    with pytest.raises(NomadDecodeError):
        task_lifecycle(body)


def test_watch_service_success_reports_deployed(httpx2_mock: respx.Router) -> None:
    """Verify a service job whose deployment reads back as successful returns DEPLOYED."""
    # Given a job with one running deployment that then resolves to successful
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {
                "ID": "d1",
                "JobID": "web",
                "Status": "successful",
                "CreateIndex": 1,
                "ModifyIndex": 2,
                "StatusDescription": "Deployment completed successfully",
                "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
            }
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching the deployment to completion
    async def go() -> Outcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await watch_deploy(
                client,
                "web",
                node_names={},
                lifecycle={},
                update=discard_panel_update,
                done_label="deployed",
            )

    outcome = asyncio.run(go())

    # Then the outcome status is DEPLOYED
    assert outcome.severity is Severity.OK
    assert outcome.name == "web"


def test_watch_service_failure_reports_failed(httpx2_mock: respx.Router) -> None:
    """Verify a service job whose deployment reads back as failed returns FAILED with detail."""
    # Given a job with one running deployment that then resolves to failed
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {
                "ID": "d1",
                "JobID": "web",
                "Status": "failed",
                "CreateIndex": 1,
                "ModifyIndex": 2,
                "StatusDescription": "Rollout timed out",
                "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 0}},
            }
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching the deployment to completion
    async def go() -> Outcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await watch_deploy(
                client,
                "web",
                node_names={},
                lifecycle={},
                update=discard_panel_update,
                done_label="deployed",
            )

    outcome = asyncio.run(go())

    # Then the outcome status is FAILED and carries the status description
    assert outcome.severity is Severity.FAIL
    assert outcome.detail == "Rollout timed out"


def test_watch_batch_all_allocs_complete_reports_deployed(httpx2_mock: respx.Router) -> None:
    """Verify a batch job with no deployments and all allocs complete returns DEPLOYED."""
    # Given a batch job with no deployments and one allocation in complete status
    httpx2_mock.get(f"{_ADDR}/v1/job/batch/deployments").respond(json=[])
    httpx2_mock.get(f"{_ADDR}/v1/job/batch/allocations").respond(json=[_ALLOC_STUB])

    # When watching the job allocations to completion
    async def go() -> Outcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await watch_deploy(
                client,
                "batch",
                node_names={},
                lifecycle={},
                update=discard_panel_update,
                done_label="deployed",
            )

    outcome = asyncio.run(go())

    # Then the outcome status is DEPLOYED
    assert outcome.severity is Severity.OK
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
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {
                "ID": "d1",
                "JobID": "web",
                "Status": "successful",
                "CreateIndex": 1,
                "ModifyIndex": 2,
                "StatusDescription": "Deployment completed successfully",
                "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
            }
        ]
    )
    # And a no-op sleep so the retry runs instantly
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When watching a job whose first poll cannot decode its allocations
    async def go() -> Outcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await watch_deploy(
                client,
                "web",
                node_names={},
                lifecycle={},
                update=discard_panel_update,
                done_label="deployed",
            )

    outcome = asyncio.run(go())

    # Then the transient error is skipped and the next poll resolves to DEPLOYED
    assert outcome.severity is Severity.OK


def test_watch_ignores_stale_successful_deployment_from_prior_run(
    httpx2_mock: respx.Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a re-run job's watch ignores the prior run's already-successful deployment."""
    # Given zero-duration timeout and poll interval so the test completes instantly
    monkeypatch.setattr(lifecycle_mod, "DEPLOY_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(lifecycle_mod, "POLL_INTERVAL_SECONDS", 0.0)

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
    async def go() -> Outcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await watch_deploy(
                client,
                "web",
                node_names={},
                lifecycle={},
                update=discard_panel_update,
                done_label="deployed",
                since_index=10,
            )

    outcome = asyncio.run(go())

    # Then the stale deployment does not short-circuit the watch; it keeps waiting
    assert outcome.severity is Severity.WARN


def test_watch_follows_fresh_deployment_past_stale_one(httpx2_mock: respx.Router) -> None:
    """Verify the watch follows this run's deployment, not an earlier one."""
    # Given a stale failed deployment (index 1) alongside this run's successful deployment
    # (index 11), returned in an order that puts the stale one first
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {
                "ID": "old",
                "JobID": "web",
                "Status": "failed",
                "CreateIndex": 1,
                "ModifyIndex": 2,
            },
            {
                "ID": "new",
                "JobID": "web",
                "Status": "successful",
                "CreateIndex": 11,
                "ModifyIndex": 12,
                "StatusDescription": "Deployment completed successfully",
                "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
            },
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching with this registration's modify index as the floor
    async def go() -> Outcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await watch_deploy(
                client,
                "web",
                node_names={},
                lifecycle={},
                update=discard_panel_update,
                done_label="deployed",
                since_index=10,
            )

    outcome = asyncio.run(go())

    # Then it follows this run's deployment, not the stale failed one, and reports DEPLOYED
    assert outcome.severity is Severity.OK


def test_watch_times_out_when_never_terminal(
    httpx2_mock: respx.Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify watch_deploy returns TIMEOUT when the deployment never reaches a terminal state."""
    # Given zero-duration timeout and poll interval so the test completes instantly
    monkeypatch.setattr(lifecycle_mod, "DEPLOY_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(lifecycle_mod, "POLL_INTERVAL_SECONDS", 0.0)

    # Given a deployment that perpetually stays in running state
    httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(
        json=[
            {
                "ID": "d1",
                "JobID": "web",
                "Status": "running",
                "CreateIndex": 1,
                "ModifyIndex": 2,
                "StatusDescription": "",
                "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 0}},
            }
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching a job that never becomes terminal
    async def go() -> Outcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await watch_deploy(
                client,
                "web",
                node_names={},
                lifecycle={},
                update=discard_panel_update,
                done_label="deployed",
            )

    outcome = asyncio.run(go())

    # Then the outcome is TIMEOUT, not a hang
    assert outcome.severity is Severity.WARN


def test_stop_and_wait_returns_stopped_when_allocs_drain(httpx2_mock: respx.Router, mocker):
    """Verify stop_and_wait reports STOPPED once allocations reach a terminal state."""
    # Given a stop call and allocations that drain running -> complete
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[_alloc_json("running")]),
            httpx.Response(200, json=[_alloc_json("complete")]),
        ]
    )
    # And a no-op sleep so the poll loop runs instantly
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping and waiting
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=discard_panel_update
            )

    outcome = asyncio.run(run())

    # Then the job is reported stopped
    assert outcome.severity is Severity.OK


def test_stop_and_wait_skips_transient_alloc_decode_error(httpx2_mock: respx.Router, mocker):
    """Verify a one-off allocation decode error skips the poll instead of failing the stop."""
    # Given a stop call whose first drain poll is undecodable, then drains to complete
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[{"unexpected": "shape"}]),
            httpx.Response(200, json=[_alloc_json("complete")]),
        ]
    )
    # And a no-op sleep so the retry runs instantly
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping and waiting through the transient decode error
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=discard_panel_update
            )

    outcome = asyncio.run(run())

    # Then the transient error is skipped and the drain resolves to STOPPED, not FAILED
    assert outcome.severity is Severity.OK


def test_stop_and_wait_times_out_when_never_terminal(httpx2_mock: respx.Router, mocker):
    """Verify stop_and_wait reports TIMEOUT when allocations never drain."""
    # Given a stop call and allocations that stay running
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[_alloc_json("running")])
    # And a tiny timeout budget plus a no-op sleep so the loop ends quickly
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)
    mocker.patch("nd.commands._lifecycle.STOP_TIMEOUT_SECONDS", 0.03)
    mocker.patch("nd.commands._lifecycle.POLL_INTERVAL_SECONDS", 0.01)

    # When stopping and waiting
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=discard_panel_update
            )

    outcome = asyncio.run(run())

    # Then the job is reported as timed out
    assert outcome.severity is Severity.WARN
    assert not outcome.workload_stopped
    assert "draining" in outcome.detail


def test_stop_and_wait_reports_phase_and_drain_detail(httpx2_mock: respx.Router, mocker):
    """Verify the poll loop reports the running task in the phase and as a detail row."""
    # Given a stop call and an allocation with a running cleanup task, then terminal
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    alloc_running = {
        **_alloc_json("running"),
        "TaskStates": {"cleanup": {"State": "running", "Failed": False, "Restarts": 0}},
    }
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[alloc_running]),
            httpx.Response(200, json=[_alloc_json("complete")]),
        ]
    )
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)
    phases: list[str] = []
    detail_labels: list[str] = []

    def _update(phase: str, children=()) -> None:
        phases.append(phase)
        detail_labels.extend(c.cells[0] for c in children)

    # When stopping and waiting, capturing the phase texts and detail rows
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=_update
            )

    outcome = asyncio.run(run())

    # Then it stops, the phase names the task still draining, and a detail row names it too
    assert outcome.severity is Severity.OK
    assert "waiting on: cleanup" in phases
    assert any("cleanup" in label for label in detail_labels)


def test_stop_and_wait_purges_after_drain(httpx2_mock: respx.Router, mocker):
    """Verify a purge stop watches the drain first, then garbage-collects the dead job."""
    # Given a job that drains running -> complete and a deregister endpoint
    stop_route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[_alloc_json("running")]),
            httpx.Response(200, json=[_alloc_json("complete")]),
        ]
    )
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping with purge=True
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=True, node_names={}, update=discard_panel_update
            )

    outcome = asyncio.run(run())

    # Then the job stops, and the deregister was issued first plain then with purge=true
    assert outcome.severity is Severity.OK
    assert [c.request.url.params["purge"] for c in stop_route.calls] == ["false", "true"]


def test_stop_and_wait_reports_drained_alloc_count(httpx2_mock: respx.Router, mocker):
    """Verify a clean stop records the terminal-frame allocation count as drained."""
    # Given two allocations that are already terminal on the first drain poll
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(
        json=[_alloc_json("complete"), _alloc_json("complete")]
    )
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping without purge
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=discard_panel_update
            )

    outcome = asyncio.run(run())

    # Then the outcome carries the count of allocations that drained
    assert outcome.severity is Severity.OK
    assert outcome.drained == 2


def test_stop_and_wait_purge_reports_drained_alloc_count(httpx2_mock: respx.Router, mocker):
    """Verify a purge stop still records the drained allocation count on its outcome."""
    # Given one allocation that is already terminal, with purge enabled
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[_alloc_json("complete")])
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping with purge=True
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=True, node_names={}, update=discard_panel_update
            )

    outcome = asyncio.run(run())

    # Then the drained count survives the purge path
    assert outcome.severity is Severity.OK
    assert outcome.drained == 1


def test_stop_and_wait_does_not_purge_on_timeout(httpx2_mock: respx.Router, mocker):
    """Verify a purge stop that never drains times out without purging the job."""
    # Given a job whose allocations stay running past a tiny timeout budget
    stop_route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[_alloc_json("running")])
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)
    mocker.patch("nd.commands._lifecycle.STOP_TIMEOUT_SECONDS", 0.03)
    mocker.patch("nd.commands._lifecycle.POLL_INTERVAL_SECONDS", 0.01)

    # When stopping with purge=True
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=True, node_names={}, update=discard_panel_update
            )

    outcome = asyncio.run(run())

    # Then it times out and the job was never purged (only the plain stop was issued)
    assert outcome.severity is Severity.WARN
    assert not outcome.workload_stopped
    assert "true" not in [c.request.url.params["purge"] for c in stop_route.calls]


def test_stop_and_wait_reports_failed_when_purge_fails(httpx2_mock: respx.Router, mocker):
    """Verify a clean stop whose follow-up purge errors is reported as FAILED."""
    # Given a job that drains immediately, with the follow-up purge call erroring
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").mock(
        side_effect=[
            httpx.Response(200, json={"EvalID": "e1"}),
            httpx.Response(500, text="boom"),
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[_alloc_json("complete")])
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping with purge=True
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=True, node_names={}, update=discard_panel_update
            )

    outcome = asyncio.run(run())

    # Then the outcome flags the purge failure distinctly from a hard stop failure
    assert outcome.severity is Severity.WARN
    assert outcome.workload_stopped
    assert "purge failed" in outcome.detail


def test_stop_and_wait_reports_failed_on_nomad_error(httpx2_mock: respx.Router):
    """Verify stop_and_wait reports FAILED when the stop call errors."""
    # Given a stop endpoint that returns a server error
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(status_code=500, text="boom")

    # When stopping and waiting
    async def run() -> StopOutcome:
        async with NomadClient(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=discard_panel_update
            )

    outcome = asyncio.run(run())

    # Then the failure is captured, not raised
    assert outcome.severity is Severity.FAIL
    assert "500" in outcome.detail


def test_running_task_names_returns_sorted_unique_running():
    """Verify running_task_names lists only running tasks, sorted and de-duplicated."""
    # Given allocations with a mix of running and dead tasks
    allocs = [
        _alloc_with_tasks("running", {"web": "dead", "backup": "running"}),
        _alloc_with_tasks("running", {"cleanup": "running", "backup": "running"}),
    ]

    # When collecting running task names
    # Then only running tasks appear, sorted and unique
    assert running_task_names(allocs) == ["backup", "cleanup"]


def test_running_task_names_empty_when_none_running():
    """Verify running_task_names is empty when no task is running."""
    # Given allocations whose tasks are all dead
    allocs = [_alloc_with_tasks("complete", {"web": "dead"})]

    # When collecting running task names
    # Then the list is empty
    assert running_task_names(allocs) == []


def test_phase_text_names_running_tasks():
    """Verify phase_text surfaces the names of tasks still draining."""
    # Given an allocation with a running cleanup task
    allocs = [_alloc_with_tasks("running", {"web": "dead", "cleanup": "running"})]

    # When building phase text
    # Then it names the task still being waited on
    assert phase_text(allocs, pending=1) == "waiting on: cleanup"


def test_phase_text_drains_when_no_task_running():
    """Verify phase_text falls back to a drain count when nothing is running."""
    # Given a non-terminal allocation with no running task
    allocs = [_alloc_with_tasks("pending", {})]

    # When building phase text
    # Then it reports the draining count
    assert phase_text(allocs, pending=1) == "draining 1 allocs"


def test_phase_text_stopping_when_no_allocs():
    """Verify phase_text reports 'stopping' before any allocations are seen."""
    # Given no allocations
    # When building phase text
    # Then it reports stopping
    assert phase_text([], pending=0) == "stopping"
