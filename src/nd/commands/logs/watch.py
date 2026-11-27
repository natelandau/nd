"""Watch a job's allocations for the log views, and stop the readers of tasks that ended.

Nomad keeps a followed log stream open after its task dies, until the allocation's files are
garbage collected, so a reader never learns from its stream that the task ended. Both log
views watch the job's allocations instead and stop a task's readers once it ends.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp

from nd.commands._lifecycle import pause_after_decode_error
from nd.commands.logs.stream import backoff_delay, print_queue
from nd.constants import (
    LOGS_FINAL_OUTPUT_GRACE_SECONDS,
    LOGS_RECONNECT_DELAYS_SECONDS,
    LOGS_WATCH_WAIT_SECONDS,
    TASK_DEAD_STATE,
    TASK_RUNNING_STATE,
)
from nd.nomad import NomadDecodeError, NomadError
from nd.ui.text import strip_terminal_controls, untrusted_markup

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine

    from nd.commands.logs.lines import LineFilter, PrefixFormatter
    from nd.commands.logs.stream import QueueItem
    from nd.nomad import NomadClient
    from nd.nomad.models.allocation import AllocListStub, TaskState

# An allocation ID and a task name
type TaskKey = tuple[str, str]
WATCH_FAILED_WARNING = "Cannot watch job {job} for task state"


def task_has_run(state: TaskState) -> bool:
    """Say whether a task has output to read: it runs, or it is dead after it ran.

    Args:
        state: The task's state.

    Returns:
        bool: False for a pending task, or a dead one that never started.
    """
    return state.state == TASK_RUNNING_STATE or (
        state.state == TASK_DEAD_STATE and bool(state.started_at)
    )


def task_has_ended(alloc: AllocListStub | None, task: str) -> bool:
    """Say whether a task can write no more output.

    Args:
        alloc: The task's allocation in the latest snapshot, or None when it is gone.
        task: The task name.

    Returns:
        bool: True when the allocation is gone or terminal, or the task is dead.
    """
    if alloc is None or alloc.is_terminal:
        return True
    state = alloc.task_states.get(task)
    return state is not None and state.state == TASK_DEAD_STATE


async def alloc_snapshots(
    client: NomadClient,
    *,
    job_id: str,
    namespace: str | None,
    retry_errors: bool = False,
    raise_first_error: bool = False,
) -> AsyncGenerator[list[AllocListStub]]:
    """Yield a job's allocations now, then again each time they change.

    A response that does not decode is retried after a pause.

    Args:
        client: The Nomad client.
        job_id: The job to watch.
        namespace: The job's namespace, or None for the configured one.
        retry_errors: Retry every other Nomad error too, with backoff, instead of raising it.
        raise_first_error: With ``retry_errors``, still raise an error of the first query, so
            a view that cannot start fails at once instead of waiting.

    Yields:
        list[AllocListStub]: The job's allocations.

    Raises:
        NomadError: If a query fails other than by a decode error and is not retried.
    """
    allocations = client.jobs.watch_allocations(
        job_id, wait_seconds=LOGS_WATCH_WAIT_SECONDS, namespace=namespace
    )
    failures = 0
    warned = False
    yielded = False
    while True:
        try:
            allocs = await anext(allocations)
        except NomadDecodeError as exc:
            await pause_after_decode_error(f"allocations of job {job_id}", exc)
            continue
        except NomadError as exc:
            if not retry_errors or (raise_first_error and not yielded):
                raise
            delay = backoff_delay(failures)
            failures += 1
            pp.debug(
                f"Retrying the allocation watch of {untrusted_markup(job_id)} in {delay}s "
                f"after: {untrusted_markup(str(exc))}"
            )
            # Once the backoff is at its longest the error is likely lasting, so say once
            # that the view can no longer end by itself
            if failures >= len(LOGS_RECONNECT_DELAYS_SECONDS) and not warned:
                warned = True
                pp.warning(
                    f"{WATCH_FAILED_WARNING.format(job=untrusted_markup(job_id))}. The view "
                    "keeps following, but misses tasks that start or stop until it can watch "
                    "again.",
                    details=[strip_terminal_controls(str(exc))],
                )
            await asyncio.sleep(delay)
            continue
        failures = 0
        warned = False
        yielded = True
        yield allocs


class LatestAllocs:
    """The latest snapshot of a job's allocations, which the readers check liveness against.

    Before the first snapshot arrives, every task counts as live.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, AllocListStub] | None = None

    @property
    def by_id(self) -> dict[str, AllocListStub]:
        """The allocations of the latest snapshot by ID; empty before the first one."""
        return self._by_id or {}

    def update(self, allocs: list[AllocListStub]) -> None:
        """Replace the snapshot with a newer one.

        Args:
            allocs: The job's allocations.
        """
        self._by_id = {alloc.id: alloc for alloc in allocs}

    def task_is_live(self, alloc_id: str, task: str) -> bool:
        """Say whether a task can still write output.

        Args:
            alloc_id: The task's allocation ID.
            task: The task name.

        Returns:
            bool: False once the snapshot shows the task ended or its allocation gone.
        """
        return self._by_id is None or not task_has_ended(self._by_id.get(alloc_id), task)


@dataclass
class _RunningReader:
    """A task's running reader, the event its backlog sets, and its pending stop, if any."""

    task: asyncio.Task[None]
    backlog_done: asyncio.Event
    stop: asyncio.Task[None] | None = None


class TaskReaders:
    """The running readers of a log view, one per allocation and task.

    Use it to start a task's readers in the view's task group and to stop them a grace
    period after the task ends, so its final output still prints.
    """

    def __init__(self, task_group: asyncio.TaskGroup) -> None:
        self._task_group = task_group
        self._readers: dict[TaskKey, _RunningReader] = {}

    @property
    def following(self) -> set[TaskKey]:
        """The tasks that have a running reader."""
        return set(self._readers)

    def start(
        self, key: TaskKey, reader: Coroutine[object, object, None], *, backlog_done: asyncio.Event
    ) -> None:
        """Run a task's reader until it returns or is stopped.

        Args:
            key: The allocation ID and task name the reader follows.
            reader: The reader coroutine.
            backlog_done: Set by the reader once its backlog is queued; the grace period of
                a stop starts only then, so a long backlog read is never cut short.
        """
        task = self._task_group.create_task(reader)
        self._readers[key] = _RunningReader(task=task, backlog_done=backlog_done)
        task.add_done_callback(lambda done: self._forget(key, done))

    def _forget(self, key: TaskKey, done: asyncio.Task[None]) -> None:
        running = self._readers.get(key)
        if running is not None and running.task is done:
            del self._readers[key]
            self._cancel_stop(running)

    def stop_after_grace(self, key: TaskKey) -> None:
        """Stop a task's reader a grace period after its backlog is queued, unless it returns.

        Args:
            key: The allocation ID and task name of the ended task.
        """
        running = self._readers.get(key)
        if running is None or running.stop is not None:
            return
        running.stop = self._task_group.create_task(self._stop_later(running))

    def cancel_stop(self, key: TaskKey) -> None:
        """Keep a task's reader running after all, as when the task runs again.

        Args:
            key: The allocation ID and task name.
        """
        running = self._readers.get(key)
        if running is not None:
            self._cancel_stop(running)

    @staticmethod
    def _cancel_stop(running: _RunningReader) -> None:
        if running.stop is not None:
            running.stop.cancel()
            running.stop = None

    @staticmethod
    async def _stop_later(running: _RunningReader) -> None:
        await running.backlog_done.wait()
        await asyncio.wait({running.task}, timeout=LOGS_FINAL_OUTPUT_GRACE_SECONDS)
        running.task.cancel()

    def cancel_all(self) -> None:
        """Stop every reader now."""
        for running in self._readers.values():
            running.task.cancel()

    async def wait_all(self) -> None:
        """Wait until no reader runs."""
        while self._readers:
            await asyncio.wait({running.task for running in self._readers.values()})


class TaskEndWatcher:
    """Watch one task's allocation, answer whether the task is live, and stop its readers.

    Use it for a view of one task: it keeps the latest snapshot for the readers' liveness
    checks, and once the task ends it stops the task's readers after the grace period.
    Query errors are retried, so a brief API failure never ends the view.
    """

    def __init__(
        self,
        client: NomadClient,
        *,
        job_id: str,
        namespace: str,
        key: TaskKey,
        readers: TaskReaders,
    ) -> None:
        self._client = client
        self._job_id = job_id
        self._namespace = namespace
        self._key = key
        self._readers = readers
        self._latest = LatestAllocs()

    def is_live(self) -> bool:
        """Say from the latest snapshot whether the task can still write output.

        Returns:
            bool: False once the snapshot shows the task ended.
        """
        return self._latest.task_is_live(*self._key)

    async def run(self) -> None:
        """Watch the job until the task ends, then stop its readers after the grace period."""
        async with contextlib.aclosing(
            alloc_snapshots(
                self._client, job_id=self._job_id, namespace=self._namespace, retry_errors=True
            )
        ) as snapshots:
            async for allocs in snapshots:
                self._latest.update(allocs)
                if not self.is_live():
                    self._readers.stop_after_grace(self._key)
                    return


async def run_log_view(
    queue: asyncio.Queue[QueueItem],
    *,
    line_filter: LineFilter,
    formatter: PrefixFormatter,
    drive: Callable[[TaskReaders], Awaitable[None]],
) -> None:
    """Run a log view's printer and readers until the view is done, then print what is left.

    Use it for every followed view, so each shuts down the same way: once ``drive``
    returns, the remaining readers are stopped, everything they queued prints, and the
    printer stops.

    Args:
        queue: The queue the readers fill and the printer drains.
        line_filter: Decides which log lines print and what they highlight.
        formatter: Builds each printed log row.
        drive: Starts the view's readers and watches the job, and returns when the view
            should end.
    """
    async with asyncio.TaskGroup() as tasks:
        printer = tasks.create_task(
            print_queue(queue, line_filter=line_filter, formatter=formatter)
        )
        readers = TaskReaders(tasks)
        await drive(readers)
        readers.cancel_all()
        await readers.wait_all()
        # Let the printer show everything the readers queued before stopping it
        await queue.join()
        printer.cancel()
