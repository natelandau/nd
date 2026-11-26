"""Tests for the shared job/alloc/task resolver."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nd.targets.alloc_target import (
    ResolvedAllocation,
    ResolvedTarget,
    SelectionError,
    resolve_alloc_task,
    resolve_allocation,
    resolve_task_in_every_alloc,
)
from nd.ui.prompts import PromptUnavailableError
from tests.builders import alloc_stub, job_stub, task_state, to_payload
from tests.helpers import NOMAD_TEST_ADDR, capture_output, run_with_client

if TYPE_CHECKING:
    import respx

    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.job import JobListStub

_WEB_TARGET = ResolvedTarget(job_name="web", alloc_id="alloc-1", task="server")


def _mock_cluster(
    httpx2_mock: respx.Router, *, jobs: list[JobListStub], allocs: list[AllocListStub] | None
) -> None:
    """Mock the job list and, unless `allocs` is None, the `web` job's allocations."""
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(j) for j in jobs])
    if allocs is not None:
        httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(
            json=[to_payload(a) for a in allocs]
        )


def _resolve(
    *,
    job_arg: str | None,
    task_arg: str | None,
    alloc_arg: str | None = None,
    running_only: bool = True,
) -> ResolvedTarget | None:
    """Resolve a target against the mocked cluster."""
    return run_with_client(
        lambda client: resolve_alloc_task(
            client=client,
            job_arg=job_arg,
            task_arg=task_arg,
            alloc_arg=alloc_arg,
            running_only=running_only,
        )
    )


def _resolve_every_alloc(*, task_arg: str | None) -> list[ResolvedTarget] | None:
    """Resolve the `web` job's task in every running allocation against the mocked cluster."""
    return run_with_client(
        lambda client: resolve_task_in_every_alloc(client=client, job_arg="web", task_arg=task_arg)
    )


def _two_running_allocs() -> list[AllocListStub]:
    """Build two running `web` allocations, each running one `server` task."""
    return [
        alloc_stub("alloc-1", task_states={"server": task_state()}),
        alloc_stub("alloc-2", task_states={"server": task_state()}),
    ]


def test_resolve_auto_selects_single_alloc_and_task(httpx2_mock: respx.Router):
    """Verify a one-job/one-alloc/one-task setup resolves with no prompts."""
    # Given one running job with one running alloc holding one running task
    _mock_cluster(
        httpx2_mock,
        jobs=[job_stub("web")],
        allocs=[alloc_stub("alloc-1", task_states={"server": task_state()})],
    )

    # When resolving with a matching job arg and no task arg
    target = _resolve(job_arg="web", task_arg=None)

    # Then the lone alloc and task are chosen automatically
    assert target == _WEB_TARGET


@pytest.mark.parametrize(
    ("job", "job_arg", "match"),
    [
        pytest.param(job_stub("web"), "zzz", "No running job matching 'zzz'", id="unmatched-job"),
        pytest.param(
            job_stub("web", status="dead"),
            "web",
            "No running job matching 'web'",
            id="named-job-not-running",
        ),
    ],
)
def test_resolve_unresolvable_job_raises(
    httpx2_mock: respx.Router, *, job: JobListStub, job_arg: str, match: str
):
    """Verify a named job that matches no running job raises SelectionError."""
    # Given a cluster whose only job does not run under the given name
    _mock_cluster(httpx2_mock, jobs=[job], allocs=None)

    # When resolving, Then it is a hard error, not a silent no-op
    with pytest.raises(SelectionError, match=match):
        _resolve(job_arg=job_arg, task_arg=None)


@pytest.mark.parametrize(
    ("alloc", "task_arg", "match"),
    [
        pytest.param(
            alloc_stub(
                "alloc-1", client_status="complete", task_states={"server": task_state("dead")}
            ),
            None,
            "No running allocations for 'web'",
            id="no-running-allocs",
        ),
        pytest.param(
            alloc_stub("alloc-1", task_states={"server": task_state()}),
            "nope",
            "No running task 'nope' in allocation alloc-1",
            id="bad-task",
        ),
        pytest.param(
            alloc_stub("alloc-1", task_states={"server": task_state("dead")}),
            None,
            "No running tasks in allocation alloc-1",
            id="no-running-tasks",
        ),
    ],
)
def test_resolve_unresolvable_alloc_or_task_raises(
    httpx2_mock: respx.Router, *, alloc: AllocListStub, task_arg: str | None, match: str
):
    """Verify a running job whose allocation or task cannot be resolved raises SelectionError."""
    # Given a running `web` job whose only allocation has no running match
    _mock_cluster(httpx2_mock, jobs=[job_stub("web")], allocs=[alloc])

    # When resolving the job, Then it is a hard error, not a silent no-op
    with pytest.raises(SelectionError, match=match):
        _resolve(job_arg="web", task_arg=task_arg)


def test_resolve_no_running_jobs_without_a_name_returns_none(httpx2_mock: respx.Router):
    """Verify no running jobs and no job argument returns None with a soft exit."""
    # Given only dead jobs (no running jobs)
    _mock_cluster(httpx2_mock, jobs=[job_stub("web", status="dead")], allocs=None)

    # When resolving with no job arg
    result = _resolve(job_arg=None, task_arg=None)

    # Then the result is None (soft exit 0)
    assert result is None


def test_resolve_running_only_false_allows_dead_target(httpx2_mock: respx.Router):
    """Verify running_only=False resolves a dead job, completed alloc, and dead task."""
    # Given a dead job whose only alloc is complete and whose only task is dead
    _mock_cluster(
        httpx2_mock,
        jobs=[job_stub("web", status="dead")],
        allocs=[
            alloc_stub(
                "alloc-1", client_status="complete", task_states={"server": task_state("dead")}
            )
        ],
    )

    # When resolving with running_only=False (the nd logs mode)
    target = _resolve(job_arg="web", task_arg=None, running_only=False)

    # Then the dead alloc and task are chosen automatically
    assert target == _WEB_TARGET


@pytest.mark.parametrize(
    ("jobs", "allocs", "match"),
    [
        pytest.param(
            [job_stub("web-api"), job_stub("web-ui")],
            None,
            "Job selection requires",
            id="ambiguous-job",
        ),
        pytest.param(
            [job_stub("web")],
            [
                alloc_stub("alloc-1", task_states={"server": task_state()}),
                alloc_stub("alloc-2", task_states={"server": task_state()}),
            ],
            "Allocation selection requires",
            id="ambiguous-alloc",
        ),
        pytest.param(
            [job_stub("web")],
            [alloc_stub("alloc-1", task_states={"server": task_state(), "sidecar": task_state()})],
            "Task selection requires",
            id="ambiguous-task",
        ),
    ],
)
def test_resolve_ambiguous_choice_off_a_terminal_raises(
    monkeypatch,
    httpx2_mock: respx.Router,
    *,
    jobs: list[JobListStub],
    allocs: list[AllocListStub] | None,
    match: str,
):
    """Verify an ambiguous job, allocation, or task refuses to prompt with no picker available."""
    # Given a cluster with several candidates at one level and a session that cannot prompt
    _mock_cluster(httpx2_mock, jobs=jobs, allocs=allocs)
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving with no --task, Then it is a hard error instead of a prompt into a pipe
    with pytest.raises(PromptUnavailableError, match=match):
        _resolve(job_arg="web", task_arg=None)


def test_resolve_unambiguous_target_needs_no_terminal(monkeypatch, httpx2_mock: respx.Router):
    """Verify a fully unambiguous target still resolves with no picker available."""
    # Given exactly one running job, allocation, and task
    _mock_cluster(
        httpx2_mock,
        jobs=[job_stub("web")],
        allocs=[alloc_stub("alloc-1", task_states={"server": task_state()})],
    )
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving, Then no prompt is needed and the target resolves
    target = _resolve(job_arg="web", task_arg=None)
    assert target == _WEB_TARGET


def test_resolve_allocation_skips_the_task_choice(monkeypatch, httpx2_mock: respx.Router):
    """Verify resolving an allocation never asks for a task, even when it runs several."""
    # Given one running allocation with two running tasks and a session that cannot prompt
    _mock_cluster(
        httpx2_mock,
        jobs=[job_stub("web")],
        allocs=[
            alloc_stub("alloc-1", task_states={"server": task_state(), "sidecar": task_state()})
        ],
    )
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving only the allocation
    result = run_with_client(lambda client: resolve_allocation(client=client, job_arg="web"))

    # Then the allocation resolves without the task prompt a task resolver would need
    assert result == ResolvedAllocation(job_name="web", alloc_id="alloc-1")


def test_resolve_alloc_arg_picks_by_id_prefix_without_a_prompt(
    monkeypatch, httpx2_mock: respx.Router
):
    """Verify an allocation ID prefix chooses among several allocations with no picker."""
    # Given two running allocations and a session that cannot prompt
    _mock_cluster(httpx2_mock, jobs=[job_stub("web")], allocs=_two_running_allocs())
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving with the start of the first allocation's ID
    target = _resolve(job_arg="web", task_arg=None, alloc_arg="alloc-1")

    # Then that allocation is chosen
    assert target == _WEB_TARGET


@pytest.mark.parametrize("alloc_arg", ["zzz", "alloc-", ""])
def test_resolve_alloc_arg_matching_other_than_one_raises(
    monkeypatch, httpx2_mock: respx.Router, alloc_arg: str
):
    """Verify an allocation ID prefix matching no allocation, or several, is a hard error."""
    # Given two running allocations and a terminal that could show a prompt
    _mock_cluster(httpx2_mock, jobs=[job_stub("web")], allocs=_two_running_allocs())
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: True)

    # When resolving with a prefix that does not pick exactly one, Then it is a hard error
    with pytest.raises(SelectionError, match=f"ID starting '{alloc_arg}'"):
        _resolve(job_arg="web", task_arg=None, alloc_arg=alloc_arg)


def test_resolve_every_alloc_targets_each_alloc_running_the_task(httpx2_mock: respx.Router):
    """Verify every running allocation with the task is targeted, and others are left out."""
    # Given two allocations running `server` and one running only `sidecar`
    allocs = [
        *_two_running_allocs(),
        alloc_stub("alloc-3", task_states={"sidecar": task_state()}),
    ]
    _mock_cluster(httpx2_mock, jobs=[job_stub("web")], allocs=allocs)

    # When resolving `server` in every allocation
    targets = _resolve_every_alloc(task_arg="server")

    # Then both allocations running `server` are targeted
    assert targets == [
        _WEB_TARGET,
        ResolvedTarget(job_name="web", alloc_id="alloc-2", task="server"),
    ]


def test_resolve_every_alloc_warns_about_a_copy_that_is_not_running(httpx2_mock: respx.Router):
    """Verify an allocation whose copy of the task is not running is skipped with a warning."""
    # Given one allocation running `server` and one where `server` is pending
    allocs = [
        alloc_stub("alloc-1", task_states={"server": task_state()}),
        alloc_stub("alloc-2", task_states={"server": task_state("pending")}),
    ]
    _mock_cluster(httpx2_mock, jobs=[job_stub("web")], allocs=allocs)
    console = capture_output()

    # When resolving `server` in every allocation
    targets = _resolve_every_alloc(task_arg="server")

    # Then only the running copy is targeted, and the skipped allocation is named
    assert targets == [_WEB_TARGET]
    assert "alloc-2" in console.export_text()


def test_resolve_every_alloc_unknown_task_raises(httpx2_mock: respx.Router):
    """Verify a task that runs in no allocation is a hard error."""
    # Given two allocations running only `server`
    _mock_cluster(httpx2_mock, jobs=[job_stub("web")], allocs=_two_running_allocs())

    # When resolving a task name none of them run, Then it is a hard error
    with pytest.raises(SelectionError, match="No running task 'nope' in any allocation"):
        _resolve_every_alloc(task_arg="nope")


def test_resolve_every_alloc_ambiguous_task_off_a_terminal_raises(
    monkeypatch, httpx2_mock: respx.Router
):
    """Verify several task names with no --task refuse to prompt when no picker is available."""
    # Given allocations running different tasks and a session that cannot prompt
    allocs = [
        alloc_stub("alloc-1", task_states={"server": task_state()}),
        alloc_stub("alloc-2", task_states={"sidecar": task_state()}),
    ]
    _mock_cluster(httpx2_mock, jobs=[job_stub("web")], allocs=allocs)
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving with no task, Then it is a hard error instead of a prompt into a pipe
    with pytest.raises(PromptUnavailableError, match="Task selection requires"):
        _resolve_every_alloc(task_arg=None)
