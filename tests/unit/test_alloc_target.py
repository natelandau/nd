"""Tests for the shared job/alloc/task resolver."""

import asyncio

import httpx
import pytest
import respx

from nd.nomad.client import NomadClient
from nd.nomad.config import NomadConfig
from nd.targets.alloc_target import ResolvedTarget, SelectionError, resolve_alloc_task
from nd.ui.prompts import PromptUnavailableError

_ADDR = "http://nomad.test:4646"


def _jobs_payload(*names_with_status: tuple[str, str]) -> list[dict]:
    return [
        {
            "ID": name,
            "Name": name,
            "Type": "service",
            "Status": status,
            "Priority": 50,
            "CreateIndex": 1,
            "ModifyIndex": 2,
        }
        for name, status in names_with_status
    ]


def _alloc_payload(alloc_id: str, *, tasks: dict[str, str], status: str = "running") -> dict:
    return {
        "ID": alloc_id,
        "Name": "n",
        "NodeID": "x",
        "JobID": "web",
        "TaskGroup": "web",
        "ClientStatus": status,
        "DesiredStatus": "run",
        "CreateIndex": 1,
        "ModifyIndex": 2,
        "TaskStates": {t: {"State": s, "Failed": False, "Restarts": 0} for t, s in tasks.items()},
    }


def _resolve(**kwargs) -> ResolvedTarget | None:
    async def _run() -> ResolvedTarget | None:
        config = NomadConfig(address=_ADDR)
        async with NomadClient.from_config(config) as client:
            return await resolve_alloc_task(client, **kwargs)

    return asyncio.run(_run())


def test_resolve_auto_selects_single_alloc_and_task(httpx2_mock: respx.Router):
    """Verify a one-job/one-alloc/one-task setup resolves with no prompts."""
    # Given one running job with one running alloc holding one running task
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(200, json=_jobs_payload(("web", "running")))
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        return_value=httpx.Response(
            200, json=[_alloc_payload("alloc-1", tasks={"server": "running"})]
        )
    )

    # When resolving with a matching job arg and no task arg
    target = _resolve(job_arg="web", task_arg=None)

    # Then the lone alloc and task are chosen automatically
    assert target == ResolvedTarget(job_name="web", alloc_id="alloc-1", task="server")


def test_resolve_unmatched_job_arg_raises(httpx2_mock: respx.Router):
    """Verify a job argument that matches no running job raises SelectionError."""
    # Given a running job that does not match the argument
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(200, json=_jobs_payload(("web", "running")))
    )

    # When resolving with a non-matching arg, Then it is a hard error
    with pytest.raises(SelectionError):
        _resolve(job_arg="zzz", task_arg=None)


def test_resolve_no_running_allocs_raises(httpx2_mock: respx.Router):
    """Verify a job with no running allocations raises SelectionError."""
    # Given a running job whose only alloc is complete
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(200, json=_jobs_payload(("web", "running")))
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        return_value=httpx.Response(
            200, json=[_alloc_payload("a", tasks={"server": "dead"}, status="complete")]
        )
    )

    # When resolving, Then it is a hard error
    with pytest.raises(SelectionError):
        _resolve(job_arg="web", task_arg=None)


def test_resolve_bad_task_arg_raises(httpx2_mock: respx.Router):
    """Verify a --task name absent from the running tasks raises SelectionError."""
    # Given a running alloc whose running task is "server"
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(200, json=_jobs_payload(("web", "running")))
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        return_value=httpx.Response(
            200, json=[_alloc_payload("alloc-1", tasks={"server": "running"})]
        )
    )

    # When resolving with a task arg that does not exist, Then it is a hard error
    with pytest.raises(SelectionError):
        _resolve(job_arg="web", task_arg="nope")


def test_resolve_no_running_jobs_returns_none(httpx2_mock: respx.Router):
    """Verify no running jobs returns None with a soft exit."""
    # Given only dead jobs (no running jobs)
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(200, json=_jobs_payload(("web", "dead")))
    )

    # When resolving with no job arg
    result = _resolve(job_arg=None, task_arg=None)

    # Then the result is None (soft exit 0)
    assert result is None


def test_resolve_running_only_false_allows_dead_target(httpx2_mock: respx.Router):
    """Verify running_only=False resolves a dead job, completed alloc, and dead task."""
    # Given a dead job whose only alloc is complete and whose only task is dead
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(200, json=_jobs_payload(("web", "dead")))
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        return_value=httpx.Response(
            200,
            json=[_alloc_payload("alloc-1", tasks={"server": "dead"}, status="complete")],
        )
    )

    # When resolving with running_only=False (the nd logs mode)
    target = _resolve(job_arg="web", task_arg=None, running_only=False)

    # Then the dead alloc and task are chosen automatically
    assert target == ResolvedTarget(job_name="web", alloc_id="alloc-1", task="server")


def test_resolve_ambiguous_job_off_a_terminal_raises(monkeypatch, httpx2_mock: respx.Router):
    """Verify an ambiguous job refuses to prompt when no picker can be shown."""
    # Given two running jobs that both contain the argument
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(
            200, json=_jobs_payload(("web-api", "running"), ("web-ui", "running"))
        )
    )
    # And a session that cannot show a picker
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving, Then it is a hard error instead of a prompt into a pipe
    with pytest.raises(PromptUnavailableError, match="Job selection requires"):
        _resolve(job_arg="web", task_arg=None)


def test_resolve_ambiguous_alloc_off_a_terminal_raises(monkeypatch, httpx2_mock: respx.Router):
    """Verify multiple running allocations refuse to prompt with no picker available."""
    # Given one running job with two running allocations
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(200, json=_jobs_payload(("web", "running")))
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        return_value=httpx.Response(
            200,
            json=[
                _alloc_payload("alloc-1", tasks={"server": "running"}),
                _alloc_payload("alloc-2", tasks={"server": "running"}),
            ],
        )
    )
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving, Then it is a hard error
    with pytest.raises(PromptUnavailableError, match="Allocation selection requires"):
        _resolve(job_arg="web", task_arg=None)


def test_resolve_ambiguous_task_off_a_terminal_raises(monkeypatch, httpx2_mock: respx.Router):
    """Verify multiple running tasks refuse to prompt with no picker available."""
    # Given one running job with one running allocation holding two running tasks
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(200, json=_jobs_payload(("web", "running")))
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        return_value=httpx.Response(
            200,
            json=[_alloc_payload("alloc-1", tasks={"server": "running", "sidecar": "running"})],
        )
    )
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving with no --task, Then it is a hard error
    with pytest.raises(PromptUnavailableError, match="Task selection requires"):
        _resolve(job_arg="web", task_arg=None)


def test_resolve_unambiguous_target_needs_no_terminal(monkeypatch, httpx2_mock: respx.Router):
    """Verify a fully unambiguous target still resolves with no picker available."""
    # Given exactly one running job, allocation, and task
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(200, json=_jobs_payload(("web", "running")))
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        return_value=httpx.Response(
            200, json=[_alloc_payload("alloc-1", tasks={"server": "running"})]
        )
    )
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: False)

    # When resolving, Then no prompt is needed and the target resolves
    target = _resolve(job_arg="web", task_arg=None)
    assert target == ResolvedTarget(job_name="web", alloc_id="alloc-1", task="server")
