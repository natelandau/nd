"""Tests for the shared job/alloc/task resolver."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nd.targets.alloc_target import (
    ResolvedTarget,
    SelectionError,
    resolve_alloc_task,
    resolve_with_client,
)
from nd.ui.prompts import PromptUnavailableError
from tests.builders import alloc_stub, job_stub, task_state, to_payload
from tests.helpers import NOMAD_TEST_ADDR, run_with_client

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
    *, job_arg: str | None, task_arg: str | None, running_only: bool = True
) -> ResolvedTarget | None:
    """Resolve a target against the mocked cluster."""
    return run_with_client(
        lambda client: resolve_alloc_task(
            client, job_arg=job_arg, task_arg=task_arg, running_only=running_only
        )
    )


def _resolve_with_client(
    *, job_arg: str | None, task_arg: str | None
) -> tuple[int, ResolvedTarget | None]:
    """Resolve a target against the mocked cluster, mapping failures to an exit code."""
    return run_with_client(
        lambda client: resolve_with_client(client, job_arg=job_arg, task_arg=task_arg)
    )


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
    ("jobs", "allocs", "job_arg", "task_arg", "match"),
    [
        pytest.param([job_stub("web")], None, "zzz", None, None, id="unmatched-job"),
        pytest.param(
            [job_stub("web")],
            [
                alloc_stub(
                    "alloc-1", client_status="complete", task_states={"server": task_state("dead")}
                )
            ],
            "web",
            None,
            None,
            id="no-running-allocs",
        ),
        pytest.param(
            [job_stub("web")],
            [alloc_stub("alloc-1", task_states={"server": task_state()})],
            "web",
            "nope",
            None,
            id="bad-task",
        ),
        pytest.param(
            [job_stub("web")],
            [alloc_stub("alloc-1", task_states={"server": task_state("dead")})],
            "web",
            None,
            "No running tasks in allocation",
            id="no-running-tasks",
        ),
        pytest.param(
            [job_stub("web", status="dead")],
            None,
            "web",
            None,
            "No running job matching 'web'",
            id="named-job-not-running",
        ),
    ],
)
def test_resolve_unresolvable_target_raises(
    httpx2_mock: respx.Router,
    *,
    jobs: list[JobListStub],
    allocs: list[AllocListStub] | None,
    job_arg: str,
    task_arg: str | None,
    match: str | None,
):
    """Verify a job, allocation, or task that cannot be resolved raises SelectionError."""
    # Given a cluster with nothing running that matches the arguments
    _mock_cluster(httpx2_mock, jobs=jobs, allocs=allocs)

    # When resolving, Then it is a hard error, not a silent no-op
    with pytest.raises(SelectionError, match=match):
        _resolve(job_arg=job_arg, task_arg=task_arg)


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


def test_resolve_with_client_returns_the_target_and_zero(httpx2_mock: respx.Router):
    """Verify a resolved target comes back paired with a zero exit code."""
    # Given exactly one running job, allocation, and task
    _mock_cluster(
        httpx2_mock,
        jobs=[job_stub("web")],
        allocs=[alloc_stub("alloc-1", task_states={"server": task_state()})],
    )

    # When resolving through an open client
    exit_code, target = _resolve_with_client(job_arg="web", task_arg=None)

    # Then the caller gets the target and a success code
    assert exit_code == 0
    assert target == _WEB_TARGET


def test_resolve_with_client_maps_a_selection_failure_to_one(httpx2_mock: respx.Router):
    """Verify a SelectionError becomes a (1, None) result instead of propagating."""
    # Given a running job that does not match the argument
    _mock_cluster(httpx2_mock, jobs=[job_stub("web")], allocs=None)

    # When resolving with a non-matching arg
    result = _resolve_with_client(job_arg="zzz", task_arg=None)

    # Then the failure is reported as an exit code, not raised at the caller
    assert result == (1, None)


def test_resolve_with_client_maps_an_unavailable_prompt_to_one(
    monkeypatch, httpx2_mock: respx.Router
):
    """Verify a PromptUnavailableError becomes a (1, None) result instead of propagating."""
    # Given two running jobs matching the argument and a session that cannot prompt
    _mock_cluster(httpx2_mock, jobs=[job_stub("web-api"), job_stub("web-ui")], allocs=None)
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving an ambiguous name
    result = _resolve_with_client(job_arg="web", task_arg=None)

    # Then the failure is reported as an exit code, not raised at the caller
    assert result == (1, None)


def test_resolve_with_client_passes_through_a_soft_exit(httpx2_mock: respx.Router):
    """Verify nothing selectable and no job argument yields a zero code and no target."""
    # Given only dead jobs
    _mock_cluster(httpx2_mock, jobs=[job_stub("web", status="dead")], allocs=None)

    # When resolving with no job arg
    result = _resolve_with_client(job_arg=None, task_arg=None)

    # Then the caller is told to exit zero with nothing to act on
    assert result == (0, None)
