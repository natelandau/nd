"""Tests for explaining a failed deployment with its failed allocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nd.commands._deploy_failure import (
    FailedAlloc,
    FailedTask,
    collect_failed_allocs,
    render_deploy_failure,
)
from nd.commands._lifecycle import DeployOutcome
from nd.commands._orchestration import Severity
from nd.constants import (
    DEPLOY_FAILURE_MAX_ALLOCS,
    DEPLOY_FAILURE_STDERR_LINES,
)
from nd.ui.links import WebUi
from tests.builders import alloc_stub, task_event, task_state
from tests.helpers import NOMAD_TEST_ADDR, capture_output, run_with_client

if TYPE_CHECKING:
    import respx

    from nd.nomad.models.allocation import AllocListStub, TaskState

_STARTED = "2026-11-24T10:00:00Z"


def _collect(allocs: list[AllocListStub], *, job_version: int = 1) -> tuple[FailedAlloc, ...]:
    """Collect failed allocations against the mocked cluster."""
    return run_with_client(
        lambda client: collect_failed_allocs(
            client, allocs, job_version=job_version, node_names={"n1": "node1"}
        )
    )


@pytest.mark.parametrize(
    ("alloc", "expected"),
    [
        pytest.param(alloc_stub(client_status="failed", job_version=1), True, id="failed-alloc"),
        pytest.param(alloc_stub(healthy=False, job_version=1), True, id="unhealthy"),
        pytest.param(
            alloc_stub(job_version=1, task_states={"app": task_state("dead", failed=True)}),
            True,
            id="failed-task",
        ),
        pytest.param(alloc_stub(healthy=True, job_version=1), False, id="healthy"),
        pytest.param(alloc_stub(healthy=None, job_version=1), False, id="health-undecided"),
        pytest.param(
            alloc_stub(client_status="failed", job_version=0), False, id="previous-version"
        ),
    ],
)
def test_collect_failed_allocs_selects_failures_of_the_deployed_version(
    alloc: AllocListStub, *, expected: bool
) -> None:
    """Verify only failed or unhealthy allocations the failed deployment placed are explained."""
    # Given one allocation of the job
    # When collecting failed allocations for job version 1
    failed = _collect([alloc])

    # Then it is explained only when it failed and belongs to the deployed version
    assert bool(failed) is expected


def test_collect_failed_allocs_keeps_the_newest_up_to_the_cap() -> None:
    """Verify a job with many failed allocations explains only the newest few."""
    # Given more failed allocations than the cap
    allocs = [
        alloc_stub(f"a{i}", client_status="failed", job_version=1, create_index=i)
        for i in range(DEPLOY_FAILURE_MAX_ALLOCS + 2)
    ]

    # When collecting failed allocations
    failed = _collect(allocs)

    # Then the newest ones are kept, newest first
    newest = [f"a{i}" for i in range(DEPLOY_FAILURE_MAX_ALLOCS + 1, 1, -1)]
    assert [a.alloc_id for a in failed] == newest


@pytest.mark.parametrize(
    ("task_states", "expected"),
    [
        pytest.param(
            {
                "app": task_state("dead", failed=True),
                "proxy": task_state("running"),
                "init": task_state("running", restarts=2),
            },
            ["app", "init"],
            id="failed-or-restarted",
        ),
        pytest.param(
            {"app": task_state("running"), "proxy": task_state("running")},
            ["app", "proxy"],
            id="none-troubled-shows-all",
        ),
    ],
)
def test_collect_failed_allocs_picks_the_tasks_that_explain_it(
    task_states: dict[str, TaskState], expected: list[str]
) -> None:
    """Verify failed or restarted tasks are shown, or every task when none is."""
    # Given an unhealthy allocation whose tasks never started, so no logs are read
    alloc = alloc_stub(healthy=False, job_version=1, task_states=task_states)

    # When collecting failed allocations
    (failed,) = _collect([alloc])

    # Then the troubled tasks are chosen, in name order
    assert [t.name for t in failed.tasks] == expected


def test_collect_failed_allocs_reads_the_end_of_stderr(httpx2_mock: respx.Router) -> None:
    """Verify a started task's stderr is read from the end, keeping only the last lines."""
    # Given a failed task that started and a stderr log longer than the line cap
    many_lines = [f"line {i}" for i in range(DEPLOY_FAILURE_STDERR_LINES + 5)]
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/a1").respond(
        text="\n".join(many_lines)
    )
    alloc = alloc_stub(
        client_status="failed",
        job_version=1,
        task_states={"app": task_state("dead", failed=True, started_at=_STARTED)},
    )

    # When collecting failed allocations
    (failed,) = _collect([alloc])

    # Then the request asks for the task's stderr from the end, and the last lines are kept
    params = route.calls.last.request.url.params
    assert (params["task"], params["type"], params["origin"]) == ("app", "stderr", "end")
    assert failed.tasks[0].stderr_lines == tuple(many_lines[-DEPLOY_FAILURE_STDERR_LINES:])


def test_collect_failed_allocs_skips_stderr_for_a_task_that_never_started(
    httpx2_mock: respx.Router,
) -> None:
    """Verify a task that never started is explained by its events alone."""
    # Given a task that failed before it started, such as an image pull failure
    alloc = alloc_stub(
        client_status="failed",
        job_version=1,
        task_states={"app": task_state("dead", failed=True, events=[task_event("Driver Failure")])},
    )

    # When collecting failed allocations
    (failed,) = _collect([alloc])

    # Then its events are kept and no log was requested
    assert [e.type for e in failed.tasks[0].events] == ["Driver Failure"]
    assert not httpx2_mock.calls


def test_collect_failed_allocs_records_an_unreadable_log(httpx2_mock: respx.Router) -> None:
    """Verify a log that cannot be read is noted on its task instead of failing the report."""
    # Given a started task whose log endpoint errors
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/a1").respond(
        status_code=500, text="node unreachable"
    )
    alloc = alloc_stub(
        client_status="failed",
        job_version=1,
        task_states={"app": task_state("dead", failed=True, started_at=_STARTED)},
    )

    # When collecting failed allocations
    (failed,) = _collect([alloc])

    # Then the task carries why its stderr is missing
    assert failed.tasks[0].stderr_error
    assert not failed.tasks[0].stderr_lines


def test_render_deploy_failure_shows_events_and_stderr_verbatim() -> None:
    """Verify each failed allocation shows its task events and stderr, brackets included."""
    # Given a failed deploy whose task logged text that looks like Rich markup
    outcome = DeployOutcome(
        name="web",
        severity=Severity.FAIL,
        label="failed",
        failed_allocs=(
            FailedAlloc(
                alloc_id="a1b2c3d4e5",
                name="web.app[0]",
                node_id="n1",
                node="node1",
                client_status="failed",
                tasks=(
                    FailedTask(
                        name="app",
                        events=(task_event("Terminated", "Exit Code: 1"),),
                        stderr_lines=("[error] missing DATABASE_URL",),
                    ),
                ),
            ),
        ),
    )
    console = capture_output()

    # When rendering it
    render_deploy_failure(outcome, ui=WebUi("http://nomad"))
    text = console.export_text()

    # Then the allocation, its event, and its stderr appear as written
    assert "web.app[0]" in text
    assert "Exit Code: 1" in text
    assert "[error] missing DATABASE_URL" in text
