"""Readers that follow task log streams into one queue, and the printer that drains it."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from nclutils import pp
from rich.text import Text

from nd.commands.logs.lines import (
    LineFilter,
    LineSplitter,
    LogLine,
    LogSource,
    PrefixFormatter,
    StreamName,
    lifecycle_line,
    lost_stream_line,
    task_subject,
)
from nd.constants import LOGS_RECONNECT_DELAYS_SECONDS
from nd.nomad import NomadError
from nd.ui import styles

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from rich.console import Console

    from nd.nomad import NomadClient

# A `Text` is a ready lifecycle line, printed as is and never filtered
type QueueItem = LogLine | Text

STREAM_CLOSED_REASON = "stream closed"
RECONNECTED_MESSAGE = "reconnected"


def backoff_delay(failures: int) -> float:
    """Return how long to wait before the next retry of a lost stream or failed watch.

    Args:
        failures: How many attempts in a row have failed before this one.

    Returns:
        float: Seconds to wait; the longest delay repeats once the failures outrun the list.
    """
    delays = LOGS_RECONNECT_DELAYS_SECONDS
    return delays[min(failures, len(delays) - 1)]


class TaskStreamReader:
    """Follow one log stream of one task, putting its lines on the shared queue.

    Run one per task and stream, through `follow_task_streams`, so the printer shows every
    task in arrival order. A lost or closed stream puts a lost-stream line, then reconnects
    with backoff while the task is live, without printing the backlog again.

    Attributes:
        source: The task to follow.
        stream: Which log stream to follow.
        backlog_lines: How many earlier lines to put before new output; 0 for none, None
            for the whole log, which is read in full before the follow continues after it.
        backlog_done: Set once the backlog is queued or the first follow opens, and however
            the reader ends, so a caller can wait for the backlog before stopping it.
    """

    def __init__(
        self,
        client: NomadClient,
        *,
        source: LogSource,
        stream: StreamName,
        backlog_lines: int | None,
        queue: asyncio.Queue[QueueItem],
        is_live: Callable[[], bool],
        show_group: bool,
    ) -> None:
        self.source = source
        self.stream: StreamName = stream
        self.backlog_lines = backlog_lines
        self.backlog_done = asyncio.Event()
        self._client = client
        self._queue = queue
        self._is_live = is_live
        self._show_group = show_group
        self._failures = 0
        # Whether the log holds any bytes; None until a read shows it
        self._log_has_bytes: bool | None = None

    async def _put_lines(self, lines: list[str]) -> None:
        for text in lines:
            await self._queue.put(LogLine(source=self.source, stream=self.stream, text=text))

    async def _put_lost(self, reason: str) -> None:
        await self._queue.put(
            lost_stream_line(self.source, reason=reason, show_group=self._show_group)
        )

    async def _put_backlog(self) -> int | None:
        """Queue the backlog, then return where the follow starts.

        Returns:
            int | None: The byte offset from the start of the log after the whole log's last
            complete line, or None to follow from the end of the log.
        """
        if self.backlog_lines is None:
            content = await self._client.allocations.read_log(
                self.source.alloc_id, task=self.source.task, stream=self.stream
            )
            # The follow resumes after the last complete line, so it completes a line the
            # read cut short instead of printing a fragment of it
            complete = content[: content.rfind(b"\n") + 1]
            self._log_has_bytes = bool(content)
            await self._put_lines(LineSplitter().feed(complete))
            return len(complete)
        lines = await self._tail(self.backlog_lines)
        await self._put_lines(lines)
        return None

    async def _tail(self, count: int) -> list[str]:
        lines = await self._client.allocations.tail_log(
            self.source.alloc_id, task=self.source.task, stream=self.stream, lines=count
        )
        self._log_has_bytes = bool(lines)
        return lines

    async def _end_position(self) -> tuple[Literal["start", "end"], int]:
        """Choose where a follow from the end of the log starts.

        Nomad reads ``origin=end`` with ``offset=0`` as the start of the log, so a follow
        from the end asks for the last byte and skips through the first newline instead.
        An empty log has no last byte, so its follow starts at the beginning.
        """
        if self._log_has_bytes is None:
            await self._tail(1)
        return ("end", 1) if self._log_has_bytes else ("start", 0)

    async def _follow(self, *, start_offset: int | None) -> None:
        splitter = LineSplitter()
        if start_offset is None:
            origin, offset = await self._end_position()
        else:
            origin, offset = "start", start_offset
        # The byte before the end is the rest of an already printed line
        skip_to_newline = origin == "end"
        try:
            async with self._client.allocations.follow_logs(
                self.source.alloc_id,
                task=self.source.task,
                stream=self.stream,
                origin=origin,
                offset=offset,
            ) as chunks:
                self.backlog_done.set()
                if self._failures:
                    await self._queue.put(
                        lifecycle_line(
                            "reconnected",
                            subject=task_subject(self.source, show_group=self._show_group),
                            message=RECONNECTED_MESSAGE,
                        )
                    )
                async for chunk in chunks:
                    # Only output proves the stream healthy; a stream that keeps closing
                    # right after it opens keeps backing off
                    self._failures = 0
                    self._log_has_bytes = True
                    if skip_to_newline:
                        newline = chunk.find(b"\n")
                        if newline == -1:
                            continue
                        chunk = chunk[newline + 1 :]  # noqa: PLW2901
                        skip_to_newline = False
                    await self._put_lines(splitter.feed(chunk))
        finally:
            # A partial line left by a lost or stopped stream never completes, since a
            # reconnect starts at the end of the log
            await self._put_lines(splitter.flush())

    async def run(self) -> None:
        """Put the backlog, then follow, reconnecting while the task is live.

        A stream that ends while the task is live counts as lost, the same as an error.
        """
        try:
            await self._run()
        finally:
            self.backlog_done.set()

    async def _run(self) -> None:
        backlog_pending = self.backlog_lines != 0
        start_offset: int | None = None
        while True:
            try:
                if backlog_pending:
                    # Tried once: a reconnect never prints the backlog
                    backlog_pending = False
                    start_offset = await self._put_backlog()
                    self.backlog_done.set()
                try:
                    await self._follow(start_offset=start_offset)
                finally:
                    # A reconnect follows from the end of the log
                    start_offset = None
            except NomadError as exc:
                await self._put_lost(str(exc))
                if not self._is_live():
                    return
            else:
                if not self._is_live():
                    return
                await self._put_lost(STREAM_CLOSED_REASON)
            await asyncio.sleep(backoff_delay(self._failures))
            self._failures += 1
            if not self._is_live():
                return


async def follow_task_streams(  # noqa: PLR0913
    client: NomadClient,
    *,
    source: LogSource,
    streams: tuple[StreamName, ...],
    backlog_lines: int | None,
    queue: asyncio.Queue[QueueItem],
    is_live: Callable[[], bool],
    show_group: bool,
    backlog_done: asyncio.Event,
) -> None:
    """Put a task's recent and new log lines of several streams on a queue until it ends.

    Args:
        client: The Nomad client.
        source: The task to follow.
        streams: The log streams to follow, one reader each.
        backlog_lines: How many earlier lines each stream puts before new output; 0 for
            none, None for the whole log.
        queue: Receives the lines and lifecycle lines.
        is_live: Says whether the task can still write output, checked when a stream ends
            or fails and again before each reconnect.
        show_group: Whether lifecycle lines include the task group.
        backlog_done: Set once every stream's backlog is on the queue, so a caller can wait
            for it before stopping the readers.
    """
    readers = [
        TaskStreamReader(
            client,
            source=source,
            stream=stream,
            backlog_lines=backlog_lines,
            queue=queue,
            is_live=is_live,
            show_group=show_group,
        )
        for stream in streams
    ]
    async with asyncio.TaskGroup() as group:
        for reader in readers:
            group.create_task(reader.run())
        for reader in readers:
            await reader.backlog_done.wait()
        backlog_done.set()


def _print_item(
    console: Console, item: QueueItem, *, line_filter: LineFilter, formatter: PrefixFormatter
) -> None:
    """Print one queued item, dropping a log line the filter rejects."""
    if isinstance(item, LogLine):
        if not line_filter.keeps(item.text):
            return
        item = formatter.format(item, line_filter)
    console.print(item, soft_wrap=True, highlight=False, markup=False)


def print_log_lines(
    lines: Iterable[QueueItem], *, line_filter: LineFilter, formatter: PrefixFormatter
) -> None:
    """Print log lines that are already in hand, through the same filter and format as the queue.

    Use it for a static view such as a tail, where no reader or queue is involved.

    Args:
        lines: The log lines and lifecycle lines to print, in order.
        line_filter: Decides which lines print and what they highlight.
        formatter: Builds each printed row.
    """
    console = pp.console()
    with console.use_theme(styles.LOG_THEME):
        for line in lines:
            _print_item(console, line, line_filter=line_filter, formatter=formatter)


async def print_queue(
    queue: asyncio.Queue[QueueItem], *, line_filter: LineFilter, formatter: PrefixFormatter
) -> None:
    """Print queued lines as they arrive, until cancelled.

    Run one per view so lines from every reader print in one order. Filters apply to log
    lines only; lifecycle lines always print.

    Args:
        queue: The queue the readers fill.
        line_filter: Decides which log lines print and what they highlight.
        formatter: Builds each printed log row.
    """
    console = pp.console()
    with console.use_theme(styles.LOG_THEME):
        while True:
            batch = [await queue.get()]
            # Print what else is already queued in one console write, so a burst of lines
            # costs one terminal flush
            while not queue.empty():
                batch.append(queue.get_nowait())
            try:
                with console:
                    for item in batch:
                        _print_item(console, item, line_filter=line_filter, formatter=formatter)
            finally:
                for _ in batch:
                    queue.task_done()
