"""The merged log view: every allocation and task of one job in one prefixed stream."""

from __future__ import annotations

import asyncio
import contextlib
import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp

from nd.commands._deploy_failure import troubled_tasks
from nd.commands.logs.lines import (
    LogLine,
    LogSource,
    PrefixFormatter,
    alloc_subject,
    lifecycle_line,
    lost_stream_line,
)
from nd.commands.logs.stream import follow_task_streams, print_log_lines
from nd.commands.logs.watch import (
    LatestAllocs,
    alloc_snapshots,
    run_log_view,
    task_has_run,
)
from nd.constants import (
    FAILED_ALLOC_STATUSES,
    LOGS_BACKLOG_LINES,
    LOGS_MAX_FAILED_ALLOCS,
    LOGS_QUEUE_MAX_ITEMS,
    TASK_DEAD_STATE,
)
from nd.nomad import NomadError, NomadNotFoundError
from nd.targets import SelectionError
from nd.ui.text import untrusted_markup

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from rich.text import Text

    from nd.commands.logs.lines import LineFilter, StreamName
    from nd.commands.logs.stream import QueueItem
    from nd.commands.logs.watch import TaskKey, TaskReaders
    from nd.nomad import NomadClient
    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.job import JobListStub
    from nd.ui.styles import LifecycleEvent


FAILED_TAIL_HEADER = "failed, last {count} lines:"
WAITING_MESSAGE = "has no live allocations, waiting for new ones"
JOB_PURGED_MESSAGE = "Job {job} was purged"


@dataclass(frozen=True)
class AllocPlan:
    """What the view does with each allocation it finds at start.

    Attributes:
        follow: Live allocations whose tasks get readers.
        failed_tail: The newest failed or lost allocations, whose last lines print once.
    """

    follow: list[AllocListStub]
    failed_tail: list[AllocListStub]


@dataclass(frozen=True)
class AllocChange:
    """What changed between two snapshots of a job's allocations.

    Attributes:
        started: Allocations seen for the first time and not yet terminal.
        stopped: Allocations that became terminal, or were first seen terminal.
        new_tasks: Allocation and task pairs that need a reader.
    """

    started: list[AllocListStub]
    stopped: list[AllocListStub]
    new_tasks: list[tuple[AllocListStub, str]]


def plan_initial(allocs: list[AllocListStub], *, max_failed: int) -> AllocPlan:
    """Sort a job's allocations at start into those to follow and those to tail once.

    A completed allocation is in neither list. A failed allocation that Nomad replaced still
    counts, because the replacement is often why the user is looking.

    Args:
        allocs: The job's allocations.
        max_failed: The most failed or lost allocations to tail.

    Returns:
        AllocPlan: Live allocations in their given order, and the newest failed ones first.
    """
    failed = sorted(
        (alloc for alloc in allocs if alloc.client_status in FAILED_ALLOC_STATUSES),
        key=lambda alloc: alloc.create_index,
        reverse=True,
    )
    return AllocPlan(
        follow=[alloc for alloc in allocs if not alloc.is_terminal],
        failed_tail=failed[:max_failed],
    )


def readable_tasks(alloc: AllocListStub, *, task_filter: str | None) -> list[str]:
    """List the tasks of an allocation that have output to read.

    A task qualifies when it runs, or is dead after it ran. A pending task, or a poststop
    task that has not run, has no log yet.

    Args:
        alloc: The allocation.
        task_filter: Keep only the task of this name, when given.

    Returns:
        list[str]: The task names, sorted.
    """
    return sorted(
        name
        for name, state in alloc.task_states.items()
        if (task_filter is None or name == task_filter) and task_has_run(state)
    )


def _was_dead(previous: AllocListStub | None, task: str) -> bool:
    state = previous.task_states.get(task) if previous is not None else None
    return state is not None and state.state == TASK_DEAD_STATE


def diff_allocs(
    previous: dict[str, AllocListStub],
    current: list[AllocListStub],
    *,
    followed: set[tuple[str, str]],
    task_filter: str | None,
) -> AllocChange:
    """Compare a new snapshot of a job's allocations with the last one.

    A readable task of a live allocation needs a reader when none follows it, unless it was
    already dead in the last snapshot: its reader finished, and rereading it would print its
    log again.

    Args:
        previous: The last snapshot, by allocation ID.
        current: The new snapshot.
        followed: The (allocation ID, task) pairs that have a reader.
        task_filter: Consider only the task of this name, when given.

    Returns:
        AllocChange: The allocations that started or stopped and the tasks that need readers.
    """
    started = [a for a in current if a.id not in previous and not a.is_terminal]
    stopped = [
        a
        for a in current
        if a.is_terminal and (a.id not in previous or not previous[a.id].is_terminal)
    ]
    new_tasks = [
        (alloc, task)
        for alloc in current
        if not alloc.is_terminal
        for task in readable_tasks(alloc, task_filter=task_filter)
        if (alloc.id, task) not in followed
        and not (
            alloc.task_states[task].state == TASK_DEAD_STATE
            and _was_dead(previous.get(alloc.id), task)
        )
    ]
    return AllocChange(started=started, stopped=stopped, new_tasks=new_tasks)


def _failure_reason(alloc: AllocListStub, *, task_filter: str | None) -> str:
    """Return the last event message of the allocation's failed task, or its client status."""
    states = {
        name: state
        for name, state in alloc.task_states.items()
        if task_filter is None or name == task_filter
    }
    # A failed task explains the allocation better than a sidecar that was stopped with it
    for _name, state in sorted(troubled_tasks(states).items()):
        if state.events:
            last = state.events[-1]
            if reason := last.display_message or last.message:
                return reason
    return alloc.client_status


class _MergedView:
    """Hold the state of one merged view: the allocations seen, readers, and output queue."""

    def __init__(
        self,
        client: NomadClient,
        *,
        job: JobListStub,
        tasks_by_group: dict[str, list[str]],
        task_filter: str | None,
        streams: tuple[StreamName, ...],
        line_filter: LineFilter,
    ) -> None:
        self._client = client
        self._job = job
        self._tasks_by_group = tasks_by_group
        self._task_filter = task_filter
        self._streams = streams
        self._line_filter = line_filter
        self._show_group = len(tasks_by_group) > 1
        self._formatter = PrefixFormatter(show_group=self._show_group, show_prefix=True)
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=LOGS_QUEUE_MAX_ITEMS)
        self._latest = LatestAllocs()
        # Tasks followed before print their backlog once only, even when followed again
        self._ever_followed: set[TaskKey] = set()
        self._announced_waiting = False

    def _selected_tasks(self, alloc: AllocListStub) -> list[str]:
        """Return the allocation's tasks that the task filter keeps."""
        # An allocation of an older job version can name a group the spec no longer has
        names = self._tasks_by_group.get(alloc.task_group) or sorted(alloc.task_states)
        return [name for name in names if self._task_filter in {None, name}]

    def select(self, allocs: list[AllocListStub]) -> list[AllocListStub]:
        """Keep the allocations that run a selected task."""
        return [alloc for alloc in allocs if self._selected_tasks(alloc)]

    @staticmethod
    def _alloc_line(alloc: AllocListStub, event: LifecycleEvent, message: str) -> Text:
        return lifecycle_line(
            event, subject=alloc_subject(group=alloc.task_group, alloc_id=alloc.id), message=message
        )

    @property
    def _waiting(self) -> bool:
        """Whether the latest snapshot has no live allocation."""
        return all(alloc.is_terminal for alloc in self._latest.by_id.values())

    async def _job_is_purged(self) -> bool:
        try:
            await self._client.jobs.get(self._job.id, namespace=self._job.namespace)
        except NomadNotFoundError:
            return True
        except NomadError as exc:
            # The watch retries a lasting failure, so the check runs again on its next snapshot
            pp.debug(
                f"Could not check whether job {untrusted_markup(self._job.name)} was purged: "
                f"{untrusted_markup(str(exc))}"
            )
        return False

    async def _stream_lines(
        self, source: LogSource, stream: StreamName, *, count: int
    ) -> list[QueueItem]:
        """Read one stream's last lines; a failed read becomes a lost-stream line."""
        try:
            texts = await self._client.allocations.tail_log(
                source.alloc_id, task=source.task, stream=stream, lines=count
            )
        except NomadError as exc:
            return [lost_stream_line(source, reason=str(exc), show_group=self._show_group)]
        return [LogLine(source=source, stream=stream, text=text) for text in texts]

    async def _task_lines(self, alloc: AllocListStub, task: str, *, count: int) -> list[QueueItem]:
        """Read a task's last lines of every stream at once, in stream order."""
        source = LogSource(group=alloc.task_group, task=task, alloc_id=alloc.id)
        per_stream = await asyncio.gather(
            *(self._stream_lines(source, stream, count=count) for stream in self._streams)
        )
        return [item for items in per_stream for item in items]

    async def _failed_tail(self, alloc: AllocListStub, *, count: int) -> list[QueueItem]:
        """Build a failed allocation's lines: one failed line, then each task's last lines.

        An allocation whose tasks never started has no log, so its line gives the reason.
        """
        started = [
            task
            for task in self._selected_tasks(alloc)
            if (state := alloc.task_states.get(task)) is not None and state.started_at
        ]
        if not started:
            reason = _failure_reason(alloc, task_filter=self._task_filter)
            return [self._alloc_line(alloc, "failed", f"failed ({reason})")]
        per_task = await asyncio.gather(
            *(self._task_lines(alloc, task, count=count) for task in started)
        )
        header: QueueItem = self._alloc_line(
            alloc, "failed", FAILED_TAIL_HEADER.format(count=count)
        )
        return [header, *(item for items in per_task for item in items)]

    async def print_tails(self, plan: AllocPlan, *, count: int, live: bool) -> None:
        """Print the failed allocations' tails and, with ``live``, every live task's last lines.

        Every log is read at once, and every line is read before any prints, so the output
        keeps a fixed order and the message column holds from the first line.
        """
        reads = [self._failed_tail(alloc, count=count) for alloc in plan.failed_tail]
        if live:
            reads.extend(
                self._task_lines(alloc, task, count=count)
                for alloc in plan.follow
                for task in readable_tasks(alloc, task_filter=self._task_filter)
            )
        items = [item for block in await asyncio.gather(*reads) for item in block]
        self._formatter.reserve(item.source for item in items if isinstance(item, LogLine))
        print_log_lines(items, line_filter=self._line_filter, formatter=self._formatter)

    def _start_reader(self, readers: TaskReaders, alloc: AllocListStub, task: str) -> None:
        key = (alloc.id, task)
        backlog = 0 if key in self._ever_followed else LOGS_BACKLOG_LINES
        self._ever_followed.add(key)
        backlog_done = asyncio.Event()
        readers.start(
            key,
            follow_task_streams(
                self._client,
                source=LogSource(group=alloc.task_group, task=task, alloc_id=alloc.id),
                streams=self._streams,
                backlog_lines=backlog,
                queue=self._queue,
                is_live=functools.partial(self._latest.task_is_live, alloc.id, task),
                show_group=self._show_group,
                backlog_done=backlog_done,
            ),
            backlog_done=backlog_done,
        )

    def _stop_line(self, alloc: AllocListStub) -> Text:
        if alloc.client_status in FAILED_ALLOC_STATUSES:
            reason = _failure_reason(alloc, task_filter=self._task_filter)
            return self._alloc_line(alloc, "failed", f"failed ({reason})")
        return self._alloc_line(alloc, "stopped", f"stopped ({alloc.client_status})")

    async def _apply(
        self, readers: TaskReaders, allocs: list[AllocListStub], *, initial: bool
    ) -> None:
        """Start and stop readers and queue lifecycle lines for a new snapshot.

        The first snapshot starts readers only: allocations that exist at start neither
        started nor stopped during the view.
        """
        change = diff_allocs(
            self._latest.by_id, allocs, followed=readers.following, task_filter=self._task_filter
        )
        # Readers check liveness against this snapshot, so store it before starting them
        self._latest.update(allocs)
        if not initial:
            for alloc in change.started:
                await self._queue.put(self._alloc_line(alloc, "started", "started"))
            for alloc in change.stopped:
                await self._queue.put(self._stop_line(alloc))
        for alloc, task in change.new_tasks:
            self._start_reader(readers, alloc, task)
        # Nomad keeps a dead task's log stream open, so the view ends its readers itself.
        # This runs after the starts so a task first seen dead stops without another snapshot.
        for key in readers.following:
            if not self._latest.task_is_live(*key):
                readers.stop_after_grace(key)
            else:
                # The task runs again, as after a restart of its allocation
                readers.cancel_stop(key)
        if self._waiting and not self._announced_waiting:
            await self._queue.put(
                lifecycle_line(
                    "waiting",
                    subject=self._job.name,
                    message=WAITING_MESSAGE,
                )
            )
        self._announced_waiting = self._waiting

    async def _watch(
        self,
        readers: TaskReaders,
        allocs: list[AllocListStub],
        snapshots: AsyncIterator[list[AllocListStub]],
    ) -> None:
        """Apply each snapshot of the job's allocations until the job is purged.

        Nomad lists no allocations for a purged job rather than failing, so the view asks
        for the job itself while no allocation is live.
        """
        await self._apply(readers, allocs, initial=True)
        while not (self._waiting and await self._job_is_purged()):
            await self._apply(readers, self.select(await anext(snapshots)), initial=False)

    async def follow(
        self, allocs: list[AllocListStub], snapshots: AsyncIterator[list[AllocListStub]]
    ) -> None:
        """Follow every readable task and watch the job until it is purged or cancelled.

        Args:
            allocs: The job's selected allocations at start.
            snapshots: The job's later allocations, one list per change.
        """

        async def drive(readers: TaskReaders) -> None:
            await self._watch(readers, allocs, snapshots)

        await run_log_view(
            self._queue, line_filter=self._line_filter, formatter=self._formatter, drive=drive
        )
        pp.info(JOB_PURGED_MESSAGE.format(job=untrusted_markup(self._job.name)))


async def _tasks_by_group(
    client: NomadClient, *, job: JobListStub, task_filter: str | None
) -> dict[str, list[str]]:
    """Read the job's task names per group, checking that ``task_filter`` names one of them.

    Raises:
        SelectionError: If ``task_filter`` matches no task of the job.
    """
    spec = await client.jobs.get(job.id, namespace=job.namespace)
    tasks_by_group = {group.name: [task.name for task in group.tasks] for group in spec.task_groups}
    names = sorted({name for names in tasks_by_group.values() for name in names})
    if task_filter is not None and task_filter not in names:
        msg = f"No task '{task_filter}' in job '{job.name}'; its tasks are: {', '.join(names)}"
        raise SelectionError(msg)
    return tasks_by_group


async def run_merged(
    client: NomadClient,
    *,
    job: JobListStub,
    task_filter: str | None,
    streams: tuple[StreamName, ...],
    tail: int | None,
    line_filter: LineFilter,
) -> None:
    """Show the logs of every allocation and task of a job in one stream.

    Prints the last lines of the newest failed allocations, then follows every live task,
    starting and stopping readers as Nomad places and stops allocations. With ``tail``, it
    prints the last lines of each task and returns instead of following. The follow ends
    when the job is purged or the caller cancels it.

    Args:
        client: The Nomad client.
        job: The job to show.
        task_filter: Show only the task of this name in every allocation, when given.
        streams: The streams to read, in print order.
        tail: Print this many last lines per task and stream and return, instead of following.
        line_filter: Decides which lines print and what they highlight.

    Raises:
        SelectionError: If ``task_filter`` matches no task of the job.
        NomadError: If the job's spec or its first allocations query fails.
    """
    # A failed query after the start is retried, so a brief API failure never ends the view
    async with contextlib.aclosing(
        alloc_snapshots(
            client,
            job_id=job.id,
            namespace=job.namespace,
            retry_errors=True,
            raise_first_error=True,
        )
    ) as snapshots:
        # Both reads finish before either result is used, so the generator is never closed
        # mid-query, and a bad task filter reports before a failed allocation query
        tasks_by_group, first = await asyncio.gather(
            _tasks_by_group(client, job=job, task_filter=task_filter),
            anext(snapshots),
            return_exceptions=True,
        )
        if isinstance(tasks_by_group, BaseException):
            raise tasks_by_group
        if isinstance(first, BaseException):
            raise first
        view = _MergedView(
            client,
            job=job,
            tasks_by_group=tasks_by_group,
            task_filter=task_filter,
            streams=streams,
            line_filter=line_filter,
        )
        allocs = view.select(first)
        plan = plan_initial(allocs, max_failed=LOGS_MAX_FAILED_ALLOCS)
        if tail is not None:
            if plan.follow or plan.failed_tail:
                await view.print_tails(plan, count=tail, live=True)
            else:
                pp.info(f"No live or failed allocations of {untrusted_markup(job.name)}")
            return
        await view.print_tails(plan, count=LOGS_BACKLOG_LINES, live=False)
        await view.follow(allocs, snapshots)
