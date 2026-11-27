"""Tests for the merged log view of every allocation and task of a job."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import httpx  # respx-bundled; used to build mocked responses
import pytest

from nd.cli import app
from nd.commands import _lifecycle as lifecycle_mod
from nd.commands.logs import stream as stream_mod
from nd.commands.logs import watch as watch_mod
from nd.commands.logs.command import EXPORT_WITH_ALL_ERROR
from nd.commands.logs.lines import LOST_STREAM_MESSAGE, LineFilter
from nd.commands.logs.merged import (
    FAILED_TAIL_HEADER,
    JOB_PURGED_MESSAGE,
    WAITING_MESSAGE,
    diff_allocs,
    plan_initial,
    readable_tasks,
    run_merged,
)
from nd.commands.logs.stream import TaskStreamReader
from nd.constants import LOGS_BACKLOG_LINES
from nd.nomad import NomadClient, NomadConfig
from nd.targets import SelectionError
from tests.builders import (
    alloc_stub,
    job_spec,
    job_stub,
    task_event,
    task_group_spec,
    task_spec,
    task_state,
    to_payload,
)
from tests.helpers import NOMAD_TEST_ADDR, capture_output

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    import respx

    from nd.nomad.models.allocation import AllocListStub, TaskState

JOBS_URL = f"{NOMAD_TEST_ADDR}/v1/jobs"
JOB_URL = f"{NOMAD_TEST_ADDR}/v1/job/web"
ALLOCATIONS_URL = f"{NOMAD_TEST_ADDR}/v1/job/web/allocations"
STARTED = "2026-11-27T10:00:00Z"


def _alloc_id(name: str) -> str:
    """Pad a short name with zeros into a full allocation ID."""
    return f"{name:0<8}-0000-0000-0000-000000000000"


def _alloc(
    name: str,
    *,
    client_status: str = "running",
    create_index: int = 1,
    task_states: dict[str, TaskState] | None = None,
) -> AllocListStub:
    """Build an allocation whose ID starts with `name`; by default its `app` task runs."""
    return alloc_stub(
        _alloc_id(name),
        client_status=client_status,
        create_index=create_index,
        task_states=task_states or {"app": task_state("running", started_at=STARTED)},
    )


def _logs_url(name: str) -> str:
    return f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/{_alloc_id(name)}"


def _mock_job(
    httpx2_mock: respx.Router, *, tasks: tuple[str, ...] = ("app",), purged_after: int = 0
) -> None:
    """Mock the job listing and spec; with `purged_after`, the spec 404s after that many reads."""
    httpx2_mock.get(JOBS_URL).respond(json=[to_payload(job_stub("web"))])
    spec = httpx.Response(
        200, json=to_payload(job_spec("web", tasks=[task_spec(name) for name in tasks]))
    )
    route = httpx2_mock.get(JOB_URL)
    if purged_after:
        route.mock(side_effect=[spec] * purged_after + [httpx.Response(404, text="not found")])
    else:
        route.mock(return_value=spec)


def _snapshots(*snapshots: list[AllocListStub]) -> list[httpx.Response]:
    """Build blocking-query responses, one per snapshot, with rising indexes."""
    return [
        httpx.Response(
            200, json=[to_payload(a) for a in allocs], headers={"X-Nomad-Index": str(n + 5)}
        )
        for n, allocs in enumerate(snapshots)
    ]


def _run_view(*, until: Callable[[], Awaitable[object]]) -> None:
    """Run the follow view of job `web` until `until` returns, then cancel it."""

    async def scenario() -> None:
        async with NomadClient(NomadConfig(address=NOMAD_TEST_ADDR)) as client:
            view = asyncio.create_task(
                run_merged(
                    client,
                    job=job_stub("web"),
                    task_filter=None,
                    streams=("stdout",),
                    tail=None,
                    line_filter=LineFilter(),
                )
            )
            try:
                await asyncio.wait_for(until(), timeout=5)
            finally:
                view.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await view

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("statuses", "max_failed", "expected_follow", "expected_failed"),
    [
        pytest.param(["running"], 3, ["a0"], [], id="running-follows"),
        pytest.param(["pending"], 3, ["a0"], [], id="pending-follows"),
        pytest.param(["failed"], 3, [], ["a0"], id="failed-tails"),
        pytest.param(["lost"], 3, [], ["a0"], id="lost-tails"),
        pytest.param(["complete"], 3, [], [], id="complete-neither"),
        pytest.param(["failed"] * 5, 3, [], ["a4", "a3", "a2"], id="newest-failed-capped"),
    ],
)
def test_plan_initial(statuses, max_failed, expected_follow, expected_failed):
    """Verify live allocations are followed and only the newest failed ones are tailed."""
    # Given allocations created in order, one per status
    allocs = [
        alloc_stub(f"a{n}", client_status=status, create_index=n)
        for n, status in enumerate(statuses)
    ]

    # When planning the start of the view
    plan = plan_initial(allocs, max_failed=max_failed)

    # Then each allocation lands where its status puts it
    assert [alloc.id for alloc in plan.follow] == expected_follow
    assert [alloc.id for alloc in plan.failed_tail] == expected_failed


@pytest.mark.parametrize(
    ("states", "task_filter", "expected"),
    [
        pytest.param({"app": task_state("running")}, None, ["app"], id="running"),
        pytest.param({"app": task_state("pending")}, None, [], id="pending"),
        pytest.param(
            {"init": task_state("dead", started_at=STARTED)}, None, ["init"], id="dead-after-run"
        ),
        pytest.param({"post": task_state("dead")}, None, [], id="dead-never-started"),
        pytest.param(
            {"proxy": task_state("running"), "app": task_state("running")},
            None,
            ["app", "proxy"],
            id="sorted",
        ),
        pytest.param(
            {"proxy": task_state("running"), "app": task_state("running")},
            "app",
            ["app"],
            id="task-filter",
        ),
    ],
)
def test_readable_tasks(states, task_filter, expected):
    """Verify a task is readable once it runs or ran, limited by the task filter."""
    # Given an allocation with the given task states
    alloc = alloc_stub("a1", task_states=states)

    # When listing its readable tasks
    tasks = readable_tasks(alloc, task_filter=task_filter)

    # Then only running tasks and tasks that ran are listed
    assert tasks == expected


@pytest.mark.parametrize(
    ("previous", "current", "followed", "expected"),
    [
        pytest.param([], [_alloc("a1")], set(), (["a1"], [], ["a1/app"]), id="new-alloc-starts"),
        pytest.param(
            [_alloc("a1")],
            [_alloc("a1", client_status="complete")],
            {("a1", "app")},
            ([], ["a1"], []),
            id="alloc-stops",
        ),
        pytest.param(
            [_alloc("a1", task_states={"app": task_state("pending")})],
            [_alloc("a1")],
            set(),
            ([], [], ["a1/app"]),
            id="pending-task-starts",
        ),
        pytest.param(
            [_alloc("a1")], [_alloc("a1")], {("a1", "app")}, ([], [], []), id="already-followed"
        ),
        pytest.param(
            [_alloc("a1", task_states={"init": task_state("dead", started_at=STARTED)})],
            [_alloc("a1", task_states={"init": task_state("dead", started_at=STARTED)})],
            set(),
            ([], [], []),
            id="dead-task-not-reread",
        ),
        pytest.param(
            [_alloc("a1", task_states={"app": task_state("dead", started_at=STARTED)})],
            [_alloc("a1")],
            set(),
            ([], [], ["a1/app"]),
            id="dead-task-runs-again",
        ),
    ],
)
def test_diff_allocs(previous, current, followed, expected):
    """Verify the watcher starts, stops, and adds readers from one snapshot to the next."""
    # Given the previous snapshot and the tasks being followed
    by_id = {alloc.id: alloc for alloc in previous}
    followed_ids = {(_alloc_id(alloc), task) for alloc, task in followed}

    # When diffing the current snapshot against it
    change = diff_allocs(by_id, current, followed=followed_ids, task_filter=None)

    # Then the change names the right allocations and tasks
    started, stopped, new_tasks = expected
    assert [alloc.id for alloc in change.started] == [_alloc_id(n) for n in started]
    assert [alloc.id for alloc in change.stopped] == [_alloc_id(n) for n in stopped]
    assert [f"{alloc.id[:2]}/{task}" for alloc, task in change.new_tasks] == new_tasks


async def _ended_run(reader: TaskStreamReader) -> None:
    """Stand in for a stream reader whose task ends at once."""
    reader.backlog_done.set()


@pytest.fixture
def no_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the readers of an ended task at once instead of after the grace period."""
    monkeypatch.setattr(watch_mod, "LOGS_FINAL_OUTPUT_GRACE_SECONDS", 0.0)


def test_merged_tail_prints_every_task(typer_runner, nomad_env, httpx2_mock: respx.Router):
    """Verify --all --tail prints each live task and each failed allocation, then exits."""
    # Given two running allocations, a failed one that ran, and a failed one that never started
    _mock_job(httpx2_mock)
    ran = _alloc(
        "f1",
        client_status="failed",
        create_index=3,
        task_states={"app": task_state("dead", failed=True, started_at=STARTED)},
    )
    never_started = _alloc(
        "f2",
        client_status="failed",
        create_index=4,
        task_states={
            "app": task_state(
                "dead", failed=True, events=[task_event("Driver Failure", "image not found")]
            )
        },
    )
    httpx2_mock.get(ALLOCATIONS_URL).mock(
        side_effect=_snapshots([_alloc("a1"), _alloc("a2"), ran, never_started])
    )
    for name in ("a1", "a2", "f1"):
        httpx2_mock.get(_logs_url(name)).respond(content=f"hello from {name}\n".encode())
    console = capture_output(width=200)

    # When tailing two lines of every task
    result = typer_runner.invoke(app, ["logs", "web", "--all", "--tail", "2", "--stdout"])

    # Then live lines carry their prefix, and each failed allocation prints its own way
    assert result.exit_code == 0
    lines = [line.strip() for line in console.export_text().splitlines()]
    assert "app[a1000000]   hello from a1" in lines
    assert "app[a2000000]   hello from a2" in lines
    assert f"x web[f1000000] {FAILED_TAIL_HEADER.format(count=2)}" in lines
    assert "app[f1000000]   hello from f1" in lines
    assert "x web[f2000000] failed (image not found)" in lines


def test_merged_tail_reads_concurrently_and_prints_in_order(
    typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify --all --tail reads every task at once but prints in allocation order."""
    # Given two running allocations, where a1's read answers only after a2's read began
    _mock_job(httpx2_mock)
    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=_snapshots([_alloc("a1"), _alloc("a2")]))
    a2_requested = asyncio.Event()

    async def a1_log(_request: httpx.Request) -> httpx.Response:
        # A sequential read never asks for a2 first, so this times out instead of hanging
        await asyncio.wait_for(a2_requested.wait(), timeout=2)
        return httpx.Response(200, content=b"hello from a1\n")

    def a2_log(_request: httpx.Request) -> httpx.Response:
        a2_requested.set()
        return httpx.Response(200, content=b"hello from a2\n")

    httpx2_mock.get(_logs_url("a1")).mock(side_effect=a1_log)
    httpx2_mock.get(_logs_url("a2")).mock(side_effect=a2_log)
    console = capture_output(width=200)

    # When tailing every task
    result = typer_runner.invoke(app, ["logs", "web", "--all", "--tail", "2", "--stdout"])

    # Then both reads overlapped, and a1 still prints before a2
    assert result.exit_code == 0
    lines = [line.strip() for line in console.export_text().splitlines()]
    assert lines == ["app[a1000000]   hello from a1", "app[a2000000]   hello from a2"]


def test_merged_tail_reports_a_failed_read(typer_runner, nomad_env, httpx2_mock: respx.Router):
    """Verify one task's failed log read prints a lost-stream line and the others still print."""
    # Given two running allocations whose first log read fails
    _mock_job(httpx2_mock)
    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=_snapshots([_alloc("a1"), _alloc("a2")]))
    httpx2_mock.get(_logs_url("a1")).respond(status_code=500, text="boom")
    httpx2_mock.get(_logs_url("a2")).respond(content=b"hello from a2\n")
    console = capture_output(width=200)

    # When tailing every task
    result = typer_runner.invoke(app, ["logs", "web", "--all", "--tail", "2", "--stdout"])

    # Then a1 reports the lost read, a2 prints, and the command succeeds
    assert result.exit_code == 0
    output = console.export_text()
    assert f"x app[a1000000] {LOST_STREAM_MESSAGE}:" in output
    assert "hello from a2" in output


def test_merged_rejects_unknown_task(typer_runner, nomad_env, httpx2_mock: respx.Router):
    """Verify --all --task with a name the job lacks fails and names the job's tasks."""
    # Given a job with tasks app and proxy
    _mock_job(httpx2_mock, tasks=("app", "proxy"))

    # When asking for a task the job does not have
    result = typer_runner.invoke(app, ["logs", "web", "--all", "--task", "nope", "--tail", "1"])

    # Then the command exits 1 with a selection error that lists the tasks
    assert result.exit_code == 1
    assert isinstance(result.exception, SelectionError)
    assert "app, proxy" in str(result.exception)


def test_watch_exits_zero_when_job_purged(typer_runner, nomad_env, httpx2_mock: respx.Router):
    """Verify the view ends with exit 0 when the job is gone while no allocation is live."""
    # Given a job with no allocations whose spec is gone after the first read
    _mock_job(httpx2_mock, purged_after=1)
    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=_snapshots([]))
    console = capture_output(width=200)

    # When following every task of the job
    result = typer_runner.invoke(app, ["logs", "web", "--all"])

    # Then the view says the job was purged and ends cleanly
    assert result.exit_code == 0
    assert JOB_PURGED_MESSAGE.format(job="web") in console.export_text()


def test_watch_retries_failed_queries_after_start(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify a failed job or allocations query after the start is retried, not fatal."""
    # Given a job whose purge check and next allocations query each fail once, after which
    # the job is purged
    monkeypatch.setattr(stream_mod, "LOGS_RECONNECT_DELAYS_SECONDS", (0.0,))
    httpx2_mock.get(JOBS_URL).respond(json=[to_payload(job_stub("web"))])
    spec_route = httpx2_mock.get(JOB_URL).mock(
        side_effect=[
            httpx.Response(200, json=to_payload(job_spec("web", tasks=[task_spec("app")]))),
            httpx.Response(500, text="boom"),
            httpx.Response(404, text="not found"),
        ]
    )
    snapshots = _snapshots([], [])
    allocations_route = httpx2_mock.get(ALLOCATIONS_URL).mock(
        side_effect=[snapshots[0], httpx.Response(500, text="boom"), snapshots[1]]
    )

    # When following every task of the job
    result = typer_runner.invoke(app, ["logs", "web", "--all"])

    # Then both failures were retried and the view ended cleanly once the job was purged
    assert result.exit_code == 0
    assert spec_route.call_count == 3
    assert allocations_route.call_count == 3


def test_merged_follow_reports_failed_allocation(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify an allocation that fails while followed prints a failed line with its last event."""
    # Given a running allocation that then fails, after which the job is purged
    _mock_job(httpx2_mock, purged_after=1)
    failed = _alloc(
        "a1",
        client_status="failed",
        task_states={
            "app": task_state(
                "dead",
                failed=True,
                started_at=STARTED,
                events=[task_event("Terminated", "Exit Code: 137")],
            )
        },
    )
    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=_snapshots([_alloc("a1")], [failed]))
    monkeypatch.setattr(TaskStreamReader, "run", _ended_run)
    console = capture_output(width=200)

    # When following every task of the job
    result = typer_runner.invoke(app, ["logs", "web", "--all"])

    # Then the failure prints with the task event as its reason
    assert result.exit_code == 0
    assert "x web[a1000000] failed (Exit Code: 137)" in console.export_text()


def test_merged_follow_reports_allocation_changes(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify the watcher reports stopped and started allocations and waits when none live."""
    # Given a1 running, then complete, then an update that does not decode, then a2 running,
    # then no allocations and a purged job
    _mock_job(httpx2_mock, purged_after=2)
    complete = _alloc("a1", client_status="complete")
    first, second, third, fourth = _snapshots(
        [_alloc("a1")], [complete], [complete, _alloc("a2")], []
    )
    garbage = httpx.Response(200, content=b"not json", headers={"X-Nomad-Index": "7"})
    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=[first, second, garbage, third, fourth])
    monkeypatch.setattr(TaskStreamReader, "run", _ended_run)
    monkeypatch.setattr(lifecycle_mod, "POLL_INTERVAL_SECONDS", 0.0)
    console = capture_output(width=200)

    # When following every task of the job
    result = typer_runner.invoke(app, ["logs", "web", "--all"])

    # Then a1 stops, the view waits, and a2 starts, in that order
    assert result.exit_code == 0
    lines = [line.strip() for line in console.export_text().splitlines()]
    stopped = lines.index("- web[a1000000] stopped (complete)")
    waiting = lines.index(f". web {WAITING_MESSAGE}")
    started = lines.index("+ web[a2000000] started")
    assert stopped < waiting < started


def test_merged_follow_refollows_without_backlog(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify a task followed again after its reader ended does not print its backlog again."""
    # Given a running task whose reader ends at once, seen in two snapshots, then a purge
    _mock_job(httpx2_mock, purged_after=1)
    responses = iter(_snapshots([_alloc("a1")], [_alloc("a1")], []))

    async def allocations(_request: httpx.Request) -> httpx.Response:
        # Yield to the loop as a real query does, so each reader runs before the next update
        await asyncio.sleep(0.01)
        return next(responses)

    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=allocations)
    backlogs: list[int | None] = []

    async def recording_run(reader: TaskStreamReader) -> None:
        backlogs.append(reader.backlog_lines)
        reader.backlog_done.set()

    monkeypatch.setattr(TaskStreamReader, "run", recording_run)

    # When following stdout of every task
    result = typer_runner.invoke(app, ["logs", "web", "--all", "--stdout"])

    # Then only the first reader asks for a backlog
    assert result.exit_code == 0
    assert backlogs == [LOGS_BACKLOG_LINES, 0]


@pytest.mark.parametrize(
    "snapshots",
    [
        pytest.param(
            [[_alloc("a1")], [_alloc("a1", client_status="complete"), _alloc("a2")]],
            id="allocation-turns-complete",
        ),
        pytest.param(
            [[_alloc("a1", task_states={"app": task_state("dead", started_at=STARTED)})]],
            id="task-first-seen-dead",
        ),
    ],
)
def test_merged_follow_stops_reader_of_ended_task(
    monkeypatch, no_grace, httpx2_mock: respx.Router, snapshots: list[list[AllocListStub]]
):
    """Verify the reader of a task that ended is stopped though Nomad keeps its stream open."""
    # Given snapshots in which a1's task ends, a watcher that then blocks, and readers that
    # never return
    httpx2_mock.get(JOB_URL).respond(json=to_payload(job_spec("web")))
    responses = iter(_snapshots(*snapshots))

    async def allocations(_request: httpx.Request) -> httpx.Response:
        response = next(responses, None)
        if response is not None:
            return response
        await asyncio.Event().wait()
        msg = "Expected the view to be cancelled while its query blocks"
        raise AssertionError(msg)

    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=allocations)
    a1_stopped = asyncio.Event()

    async def endless_run(reader: TaskStreamReader) -> None:
        reader.backlog_done.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if reader.source.alloc_id == _alloc_id("a1"):
                a1_stopped.set()
            raise

    monkeypatch.setattr(TaskStreamReader, "run", endless_run)

    # When the view runs until a1's reader stops
    # Then it stops before the timeout, while the view still runs
    _run_view(until=a1_stopped.wait)


def test_merged_follow_keeps_reader_of_revived_task(monkeypatch, httpx2_mock: respx.Router):
    """Verify a task that runs again within the grace period keeps its reader."""
    # Given a task that runs, is dead, then runs again, and a reader that never returns
    httpx2_mock.get(JOB_URL).respond(json=to_payload(job_spec("web")))
    monkeypatch.setattr(watch_mod, "LOGS_FINAL_OUTPUT_GRACE_SECONDS", 0.05)
    dead = _alloc("a1", task_states={"app": task_state("dead", started_at=STARTED)})
    responses = iter(_snapshots([_alloc("a1")], [dead], [_alloc("a1")]))

    async def allocations(_request: httpx.Request) -> httpx.Response:
        response = next(responses, None)
        if response is not None:
            return response
        # Later queries block like a quiet job's
        await asyncio.Event().wait()
        msg = "Expected the view to be cancelled while its query blocks"
        raise AssertionError(msg)

    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=allocations)
    stopped = asyncio.Event()

    async def endless_run(reader: TaskStreamReader) -> None:
        reader.backlog_done.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.set()
            raise

    monkeypatch.setattr(TaskStreamReader, "run", endless_run)
    stopped_during_view: list[bool] = []

    async def outlast_the_grace() -> None:
        await asyncio.sleep(0.3)
        stopped_during_view.append(stopped.is_set())

    # When the view runs well past the grace period
    _run_view(until=outlast_the_grace)

    # Then the reader was not stopped while the view ran
    assert stopped_during_view == [False]


def test_merged_view_cancel_exits_cleanly(monkeypatch, httpx2_mock: respx.Router):
    """Verify cancelling the view mid-stream leaves no task running."""
    # Given one running allocation whose readers never end and a watcher that blocks
    httpx2_mock.get(JOB_URL).respond(json=to_payload(job_spec("web")))
    readers_started = asyncio.Event()

    async def endless_run(_reader: TaskStreamReader) -> None:
        readers_started.set()
        await asyncio.Event().wait()

    async def allocations(request: httpx.Request) -> httpx.Response:
        if request.url.params["index"] != "0":
            await asyncio.Event().wait()
        return _snapshots([_alloc("a1")])[0]

    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=allocations)
    monkeypatch.setattr(TaskStreamReader, "run", endless_run)

    async def scenario() -> set[asyncio.Task[object]]:
        async with NomadClient(NomadConfig(address=NOMAD_TEST_ADDR)) as client:
            view = asyncio.create_task(
                run_merged(
                    client,
                    job=job_stub("web"),
                    task_filter=None,
                    streams=("stdout", "stderr"),
                    tail=None,
                    line_filter=LineFilter(),
                )
            )
            await asyncio.wait_for(readers_started.wait(), timeout=5)

            # When the view is cancelled while its readers stream
            view.cancel()
            with pytest.raises(asyncio.CancelledError):
                await view
        return asyncio.all_tasks() - {asyncio.current_task()}

    leftover = asyncio.run(scenario())

    # Then no reader, printer, or watcher task is left behind
    assert leftover == set()


def test_merged_group_prefix_when_job_has_several_groups(
    typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify the prefix names the group when the job has more than one task group."""
    # Given a job with two groups and a running allocation of the first
    httpx2_mock.get(JOBS_URL).respond(json=[to_payload(job_stub("web"))])
    httpx2_mock.get(JOB_URL).respond(
        json=to_payload(job_spec("web", groups=[task_group_spec("web"), task_group_spec("cache")]))
    )
    httpx2_mock.get(ALLOCATIONS_URL).mock(side_effect=_snapshots([_alloc("a1")]))
    httpx2_mock.get(_logs_url("a1")).respond(content=b"hello\n")
    console = capture_output(width=200)

    # When tailing every task
    result = typer_runner.invoke(app, ["logs", "web", "--all", "--tail", "1", "--stdout"])

    # Then the prefix carries the group
    assert result.exit_code == 0
    assert "web/app[a1000000]" in console.export_text()


def test_merged_rejects_export(typer_runner, nomad_env, httpx2_mock: respx.Router, tmp_path: Path):
    """Verify --all with --export is a usage error that makes no request."""
    # When combining --all with --export
    result = typer_runner.invoke(
        app, ["logs", "web", "--all", "--export", str(tmp_path / "out.log")]
    )

    # Then the command is a usage error that names the conflict and never reaches Nomad
    assert result.exit_code == 2
    assert EXPORT_WITH_ALL_ERROR in result.output
    assert not httpx2_mock.calls
