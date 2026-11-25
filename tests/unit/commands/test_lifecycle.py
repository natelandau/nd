"""Tests for watching a job deploy or drain to a terminal state."""

from __future__ import annotations

from pathlib import Path
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
from nd.nomad import NomadDecodeError
from nd.nomad.models.deployment import TaskGroupDeploymentState
from tests.builders import alloc_stub, deployment, job_stub, task_state, to_payload
from tests.helpers import NOMAD_TEST_ADDR, discard_panel_update, run_with_client

if TYPE_CHECKING:
    import respx

    from nd.nomad.models.allocation import AllocListStub
    from nd.ui.live_panel import PanelUpdate


def _watch(job_id: str = "web", *, since_index: int = 0) -> Outcome:
    """Watch a job's deploy against the mocked cluster, discarding panel updates."""
    return run_with_client(
        lambda client: watch_deploy(
            client,
            job_id,
            node_names={},
            lifecycle={},
            update=discard_panel_update,
            done_label="deployed",
            since_index=since_index,
        )
    )


def _stop_web(*, purge: bool, update: PanelUpdate = discard_panel_update) -> StopOutcome:
    """Stop the `web` job against the mocked cluster and wait for its allocations to drain."""
    return run_with_client(
        lambda client: stop_and_wait(
            client, job_stub("web"), purge=purge, node_names={}, update=update
        )
    )


def test_deploy_phase_reports_health() -> None:
    """Verify the deploy phase summarizes healthy/desired allocations."""
    # Given a deployment with two task groups
    rollout = deployment(
        "web",
        task_groups={
            "app": TaskGroupDeploymentState(healthy_allocs=1, desired_total=2),
            "sidecar": TaskGroupDeploymentState(healthy_allocs=0, desired_total=1),
        },
    )

    # When computing the deploy phase string
    result = deploy_phase(rollout)

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


_COMPILED_JOBS = Path(__file__).parents[2] / "fixtures" / "compiled_jobs"


@pytest.mark.parametrize("fixture", sorted(_COMPILED_JOBS.glob("*.json")), ids=lambda p: p.stem)
def test_task_lifecycle_decodes_real_compiled_output(fixture: Path) -> None:
    """Verify `nomad job run -output` bodies decode, including the nulls Nomad emits."""
    # Given real compiled output, which sends null for unset Type, Status, and resources
    body = fixture.read_bytes()

    # When parsing it
    lifecycle = task_lifecycle(body)

    # Then every group is read
    assert lifecycle


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
    # Given a job with one deployment that resolves to successful
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/deployments").respond(
        json=[
            to_payload(
                deployment(
                    "web",
                    status="successful",
                    status_description="Deployment completed successfully",
                    task_groups={
                        "app": TaskGroupDeploymentState(desired_total=1, healthy_allocs=1)
                    },
                )
            )
        ]
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching the deployment to completion
    outcome = _watch()

    # Then the outcome status is DEPLOYED
    assert outcome.severity is Severity.OK
    assert outcome.name == "web"


def test_watch_service_failure_reports_failed(httpx2_mock: respx.Router) -> None:
    """Verify a service job whose deployment reads back as failed returns FAILED with detail."""
    # Given a job with one deployment that resolves to failed
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/deployments").respond(
        json=[
            to_payload(
                deployment(
                    "web",
                    status="failed",
                    status_description="Rollout timed out",
                    task_groups={"app": TaskGroupDeploymentState(desired_total=1)},
                )
            )
        ]
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching the deployment to completion
    outcome = _watch()

    # Then the outcome status is FAILED and carries the status description
    assert outcome.severity is Severity.FAIL
    assert outcome.detail == "Rollout timed out"


def test_watch_batch_all_allocs_complete_reports_deployed(httpx2_mock: respx.Router) -> None:
    """Verify a batch job with no deployments and all allocs complete returns DEPLOYED."""
    # Given a batch job with no deployments and one allocation in complete status
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/batch/deployments").respond(json=[])
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/batch/allocations").respond(
        json=[to_payload(alloc_stub(job_id="batch", task_group="batch", client_status="complete"))]
    )

    # When watching the job allocations to completion
    outcome = _watch("batch")

    # Then the outcome status is DEPLOYED
    assert outcome.severity is Severity.OK
    assert outcome.name == "batch"


def test_watch_skips_transient_alloc_decode_error(httpx2_mock: respx.Router, mocker) -> None:
    """Verify a one-off allocation decode error skips the poll instead of failing the deploy."""
    # Given the first allocations poll returns an undecodable body, then a clean one
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[{"unexpected": "shape"}]),
            httpx.Response(200, json=[]),
        ]
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/deployments").respond(
        json=[
            to_payload(
                deployment(
                    "web",
                    status="successful",
                    status_description="Deployment completed successfully",
                    task_groups={
                        "app": TaskGroupDeploymentState(desired_total=1, healthy_allocs=1)
                    },
                )
            )
        ]
    )
    # And a no-op sleep so the retry runs instantly
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When watching a job whose first poll cannot decode its allocations
    outcome = _watch()

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
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/deployments").respond(
        json=[to_payload(deployment("web", status="successful", create_index=1))]
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching with the new registration's modify index as the floor
    outcome = _watch(since_index=10)

    # Then the stale deployment does not short-circuit the watch; it keeps waiting
    assert outcome.severity is Severity.WARN


def _deployment_at(status: str, create_index: int) -> dict[str, object]:
    """Build a deployment payload created at ``create_index``."""
    return to_payload(deployment("web", status=status, create_index=create_index))


@pytest.mark.parametrize(
    ("deployments", "expected"),
    [
        pytest.param(
            [_deployment_at("failed", 1), _deployment_at("successful", 11)],
            Severity.OK,
            id="stale-failed-before-this-run",
        ),
        pytest.param(
            [_deployment_at("successful", 12), _deployment_at("failed", 11)],
            Severity.FAIL,
            id="rollback-after-this-run",
        ),
    ],
)
def test_watch_follows_this_runs_deployment(
    httpx2_mock: respx.Router, deployments: list[dict[str, object]], expected: Severity
) -> None:
    """Verify the watch follows this run's deployment, not an earlier or a later one."""
    # Given this run's deployment (index 11) beside an earlier stale one or a later
    # auto-revert rollback, in an order that does not put this run's first
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/deployments").respond(json=deployments)
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching with this registration's modify index as the floor
    outcome = _watch(since_index=10)

    # Then the outcome reflects this run's deployment
    assert outcome.severity is expected


def test_watch_times_out_when_never_terminal(
    httpx2_mock: respx.Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify watch_deploy returns TIMEOUT when the deployment never reaches a terminal state."""
    # Given zero-duration timeout and poll interval so the test completes instantly
    monkeypatch.setattr(lifecycle_mod, "DEPLOY_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(lifecycle_mod, "POLL_INTERVAL_SECONDS", 0.0)

    # Given a deployment that perpetually stays in running state
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/deployments").respond(
        json=[
            to_payload(
                deployment(
                    "web",
                    status="running",
                    task_groups={"app": TaskGroupDeploymentState(desired_total=1)},
                )
            )
        ]
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(json=[])

    # When watching a job that never becomes terminal
    outcome = _watch()

    # Then the outcome is TIMEOUT, not a hang
    assert outcome.severity is Severity.WARN


def test_stop_and_wait_returns_stopped_when_allocs_drain(httpx2_mock: respx.Router, mocker):
    """Verify stop_and_wait reports STOPPED once allocations reach a terminal state."""
    # Given a stop call and allocations that drain running -> complete
    httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[to_payload(alloc_stub(client_status="running"))]),
            httpx.Response(200, json=[to_payload(alloc_stub(client_status="complete"))]),
        ]
    )
    # And a no-op sleep so the poll loop runs instantly
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping and waiting
    outcome = _stop_web(purge=False)

    # Then the job is reported stopped
    assert outcome.severity is Severity.OK


def test_stop_and_wait_skips_transient_alloc_decode_error(httpx2_mock: respx.Router, mocker):
    """Verify a one-off allocation decode error skips the poll instead of failing the stop."""
    # Given a stop call whose first drain poll is undecodable, then drains to complete
    httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[{"unexpected": "shape"}]),
            httpx.Response(200, json=[to_payload(alloc_stub(client_status="complete"))]),
        ]
    )
    # And a no-op sleep so the retry runs instantly
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping and waiting through the transient decode error
    outcome = _stop_web(purge=False)

    # Then the transient error is skipped and the drain resolves to STOPPED, not FAILED
    assert outcome.severity is Severity.OK


def test_stop_and_wait_times_out_when_never_terminal(httpx2_mock: respx.Router, mocker):
    """Verify stop_and_wait reports TIMEOUT when allocations never drain."""
    # Given a stop call and allocations that stay running
    httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(
        json=[to_payload(alloc_stub(client_status="running"))]
    )
    # And a zero timeout budget so the loop gives up after one poll
    mocker.patch("nd.commands._lifecycle.STOP_TIMEOUT_SECONDS", 0.0)

    # When stopping and waiting
    outcome = _stop_web(purge=False)

    # Then the job is reported as timed out
    assert outcome.severity is Severity.WARN
    assert not outcome.workload_stopped
    assert "draining" in outcome.detail


def test_stop_and_wait_reports_phase_and_drain_detail(httpx2_mock: respx.Router, mocker):
    """Verify the poll loop reports the running task in the phase and as a detail row."""
    # Given a stop call and an allocation with a running cleanup task, then terminal
    httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    alloc_running = alloc_stub(
        client_status="running", task_states={"cleanup": task_state("running")}
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[to_payload(alloc_running)]),
            httpx.Response(200, json=[to_payload(alloc_stub(client_status="complete"))]),
        ]
    )
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)
    phases: list[str] = []
    detail_labels: list[str] = []

    def _update(phase: str, children=()) -> None:
        phases.append(phase)
        detail_labels.extend(c.cells[0] for c in children)

    # When stopping and waiting, capturing the phase texts and detail rows
    outcome = _stop_web(purge=False, update=_update)

    # Then it stops, the phase names the task still draining, and a detail row names it too
    assert outcome.severity is Severity.OK
    assert "waiting on: cleanup" in phases
    assert any("cleanup" in label for label in detail_labels)


def test_stop_and_wait_purges_after_drain(httpx2_mock: respx.Router, mocker):
    """Verify a purge stop watches the drain first, then garbage-collects the dead job."""
    # Given a job that drains running -> complete and a deregister endpoint
    stop_route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[to_payload(alloc_stub(client_status="running"))]),
            httpx.Response(200, json=[to_payload(alloc_stub(client_status="complete"))]),
        ]
    )
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping with purge=True
    outcome = _stop_web(purge=True)

    # Then the job stops, and the deregister was issued first plain then with purge=true
    assert outcome.severity is Severity.OK
    assert [c.request.url.params["purge"] for c in stop_route.calls] == ["false", "true"]


@pytest.mark.parametrize(
    ("purge", "alloc_count"),
    [
        pytest.param(False, 2, id="stop"),
        pytest.param(True, 1, id="purge"),
    ],
)
def test_stop_and_wait_reports_drained_alloc_count(
    httpx2_mock: respx.Router, mocker, *, purge: bool, alloc_count: int
):
    """Verify a clean stop, with or without purge, records the drained allocation count."""
    # Given allocations that are already terminal on the first drain poll
    httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(
        json=[to_payload(alloc_stub(client_status="complete"))] * alloc_count
    )
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping
    outcome = _stop_web(purge=purge)

    # Then the outcome carries the count of allocations that drained
    assert outcome.severity is Severity.OK
    assert outcome.drained == alloc_count


def test_stop_and_wait_does_not_purge_on_timeout(httpx2_mock: respx.Router, mocker):
    """Verify a purge stop that never drains times out without purging the job."""
    # Given a job whose allocations stay running past a zero timeout budget
    stop_route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(
        json=[to_payload(alloc_stub(client_status="running"))]
    )
    mocker.patch("nd.commands._lifecycle.STOP_TIMEOUT_SECONDS", 0.0)

    # When stopping with purge=True
    outcome = _stop_web(purge=True)

    # Then it times out and the job was never purged (only the plain stop was issued)
    assert outcome.severity is Severity.WARN
    assert not outcome.workload_stopped
    assert "true" not in [c.request.url.params["purge"] for c in stop_route.calls]


def test_stop_and_wait_reports_failed_when_purge_fails(httpx2_mock: respx.Router, mocker):
    """Verify a clean stop whose follow-up purge errors is reported as FAILED."""
    # Given a job that drains immediately, with the follow-up purge call erroring
    httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").mock(
        side_effect=[
            httpx.Response(200, json={"EvalID": "e1"}),
            httpx.Response(500, text="boom"),
        ]
    )
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(
        json=[to_payload(alloc_stub(client_status="complete"))]
    )
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When stopping with purge=True
    outcome = _stop_web(purge=True)

    # Then the outcome flags the purge failure distinctly from a hard stop failure
    assert outcome.severity is Severity.WARN
    assert outcome.workload_stopped
    assert "purge failed" in outcome.detail


def test_stop_and_wait_reports_failed_on_nomad_error(httpx2_mock: respx.Router):
    """Verify stop_and_wait reports FAILED when the stop call errors."""
    # Given a stop endpoint that returns a server error
    httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(status_code=500, text="boom")

    # When stopping and waiting
    outcome = _stop_web(purge=False)

    # Then the failure is captured, not raised
    assert outcome.severity is Severity.FAIL
    assert "500" in outcome.detail


@pytest.mark.parametrize(
    ("allocs", "expected"),
    [
        pytest.param(
            [
                alloc_stub(
                    client_status="running",
                    task_states={"web": task_state("dead"), "backup": task_state("running")},
                ),
                alloc_stub(
                    client_status="running",
                    task_states={"cleanup": task_state("running"), "backup": task_state("running")},
                ),
            ],
            ["backup", "cleanup"],
            id="sorted-unique-running",
        ),
        pytest.param(
            [alloc_stub(client_status="complete", task_states={"web": task_state("dead")})],
            [],
            id="none-running",
        ),
    ],
)
def test_running_task_names_returns_sorted_unique_running(
    *, allocs: list[AllocListStub], expected: list[str]
):
    """Verify running_task_names lists only running tasks, sorted and de-duplicated."""
    # Given allocations with a mix of running and dead tasks
    # When collecting running task names
    # Then only running tasks appear, sorted and unique
    assert running_task_names(allocs) == expected


@pytest.mark.parametrize(
    ("allocs", "pending", "expected"),
    [
        pytest.param(
            [
                alloc_stub(
                    client_status="running",
                    task_states={"web": task_state("dead"), "cleanup": task_state("running")},
                )
            ],
            1,
            "waiting on: cleanup",
            id="names-running-tasks",
        ),
        pytest.param(
            [alloc_stub(client_status="pending", task_states={})],
            1,
            "draining 1 allocs",
            id="no-task-running",
        ),
        pytest.param([], 0, "stopping", id="no-allocs"),
    ],
)
def test_phase_text_describes_the_drain(
    *, allocs: list[AllocListStub], pending: int, expected: str
):
    """Verify phase_text names draining tasks, else counts draining allocs, else says stopping."""
    # Given allocations in the parametrized drain state
    # When building phase text
    # Then it describes what the stop is waiting on
    assert phase_text(allocs, pending=pending) == expected
