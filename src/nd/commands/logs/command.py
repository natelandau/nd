"""The ``nd logs`` command: stream, tail, or export one task's logs, or all of a job's."""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Annotated

import typer
from nclutils import pp

from nd.commands import _common
from nd.commands._common import VerboseOption, command_app, configure_verbosity
from nd.commands.logs.lines import (
    InvalidPatternError,
    LineFilter,
    LogLine,
    LogSource,
    PrefixFormatter,
    StreamName,
)
from nd.commands.logs.merged import run_merged
from nd.commands.logs.stream import follow_task_streams, print_log_lines
from nd.commands.logs.watch import TaskEndWatcher, run_log_view
from nd.constants import LOGS_QUEUE_MAX_ITEMS
from nd.nomad import NomadClient, NomadConfig
from nd.nomad.resources.allocations import split_log_lines
from nd.targets import resolve_job
from nd.ui.links import file_link
from nd.ui.text import untrusted_markup

if TYPE_CHECKING:
    from nd.commands.logs.stream import QueueItem
    from nd.commands.logs.watch import TaskReaders
    from nd.targets import ResolvedTarget

app = command_app()
EXPORT_WITH_ALL_ERROR = "--export does not work with --all"


def _streams(*, only_stdout: bool, only_stderr: bool) -> tuple[StreamName, ...]:
    """Resolve the stream-selection flags to the streams to read (default both)."""
    if only_stdout and not only_stderr:
        return ("stdout",)
    if only_stderr and not only_stdout:
        return ("stderr",)
    return ("stdout", "stderr")


async def _follow(
    client: NomadClient,
    *,
    target: ResolvedTarget,
    source: LogSource,
    streams: tuple[StreamName, ...],
    line_filter: LineFilter,
    formatter: PrefixFormatter,
) -> None:
    """Print the streams' lines in arrival order until the task ends or every stream ends."""
    queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=LOGS_QUEUE_MAX_ITEMS)
    key = (target.alloc_id, target.task)

    async def drive(readers: TaskReaders) -> None:
        watcher = TaskEndWatcher(
            client, job_id=target.job_id, namespace=target.namespace, key=key, readers=readers
        )
        backlog_done = asyncio.Event()
        readers.start(
            key,
            follow_task_streams(
                client,
                source=source,
                streams=streams,
                # Start from the beginning of the log, as `nomad alloc logs -f` does
                backlog_lines=None,
                queue=queue,
                is_live=watcher.is_live,
                show_group=False,
                backlog_done=backlog_done,
            ),
            backlog_done=backlog_done,
        )
        async with asyncio.TaskGroup() as watching:
            watch = watching.create_task(watcher.run())
            await readers.wait_all()
            watch.cancel()

    await run_log_view(queue, line_filter=line_filter, formatter=formatter, drive=drive)


async def _print_tail(
    client: NomadClient,
    *,
    source: LogSource,
    streams: tuple[StreamName, ...],
    count: int,
    line_filter: LineFilter,
    formatter: PrefixFormatter,
) -> None:
    """Print the last lines of each stream in turn, reading every stream at once."""
    per_stream = await asyncio.gather(
        *(
            client.allocations.tail_log(
                source.alloc_id, task=source.task, stream=stream, lines=count
            )
            for stream in streams
        )
    )
    lines = [
        LogLine(source=source, stream=stream, text=line)
        for stream, texts in zip(streams, per_stream, strict=True)
        for line in texts
    ]
    print_log_lines(lines, line_filter=line_filter, formatter=formatter)


async def _export(
    client: NomadClient,
    *,
    source: LogSource,
    streams: tuple[StreamName, ...],
    tail: int | None,
    export_path: Path,
    line_filter: LineFilter,
) -> None:
    """Write each stream's log, whole or last N lines, to a file with no color or markers.

    Include and exclude patterns apply; highlight does not.
    """

    async def read(stream: StreamName) -> list[str]:
        if tail is not None:
            return await client.allocations.tail_log(
                source.alloc_id, task=source.task, stream=stream, lines=tail, keepends=True
            )
        content = await client.allocations.read_log(
            source.alloc_id, task=source.task, stream=stream
        )
        return split_log_lines(content.decode(errors="replace"), keepends=True)

    per_stream = await asyncio.gather(*(read(stream) for stream in streams))
    texts = [
        line for lines in per_stream for line in lines if line_filter.keeps(line.rstrip("\r\n"))
    ]
    # Written once, at the end; a blocking write of one local file is not worth a thread
    export_path.write_text("".join(texts), encoding="utf-8")  # noqa: ASYNC240
    pp.success(f"Wrote logs to {file_link(export_path, untrusted_markup(str(export_path)))}")


async def run_single(
    client: NomadClient,
    *,
    target: ResolvedTarget,
    streams: tuple[StreamName, ...],
    tail: int | None,
    export_path: Path | None,
    line_filter: LineFilter,
) -> None:
    """Follow, tail, or export the logs of one task.

    Args:
        client: The Nomad client.
        target: The job, allocation, and task to read.
        streams: The streams to read, in print order.
        tail: Print this many last lines per stream and return, instead of following.
        export_path: Write the logs to this file and return, instead of following.
        line_filter: Decides which lines print and what they highlight.
    """
    # The group is never shown without a prefix, so the job name fills it
    source = LogSource(group=target.job_name, task=target.task, alloc_id=target.alloc_id)
    if export_path is not None:
        await _export(
            client,
            source=source,
            streams=streams,
            tail=tail,
            export_path=export_path,
            line_filter=line_filter,
        )
        return
    formatter = PrefixFormatter(show_group=False, show_prefix=False)
    if tail is not None:
        await _print_tail(
            client,
            source=source,
            streams=streams,
            count=tail,
            line_filter=line_filter,
            formatter=formatter,
        )
        return
    await _follow(
        client,
        target=target,
        source=source,
        streams=streams,
        line_filter=line_filter,
        formatter=formatter,
    )


async def _run_all(
    config: NomadConfig,
    *,
    job: str | None,
    task: str | None,
    streams: tuple[StreamName, ...],
    tail: int | None,
    line_filter: LineFilter,
) -> None:
    async with NomadClient(config) as client:
        resolved = await resolve_job(client, job_arg=job)
        if resolved is None:
            return
        await run_merged(
            client,
            job=resolved,
            task_filter=task,
            streams=streams,
            tail=tail,
            line_filter=line_filter,
        )


async def _run(
    config: NomadConfig,
    *,
    job: str | None,
    task: str | None,
    streams: tuple[StreamName, ...],
    tail: int | None,
    export_path: Path | None,
    line_filter: LineFilter,
) -> None:
    # running_only=False so logs of a dead, completed, or failed task stay reachable
    # (debugging a crash is the main reason to read logs).
    target = await _common.resolve_target(config, job_arg=job, task_arg=task, running_only=False)
    if target is None:
        return
    async with NomadClient(config) as client:
        await run_single(
            client,
            target=target,
            streams=streams,
            tail=tail,
            export_path=export_path,
            line_filter=line_filter,
        )


@app.callback(invoke_without_command=True)
def logs(  # noqa: PLR0913
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(
            help="Job to read; matches any job whose name contains this. Omit to pick from a list."
        ),
    ] = None,
    task: Annotated[
        str | None,
        typer.Option(
            "--task",
            "-t",
            help="Target task; skips the task prompt. With --all, show only this task.",
        ),
    ] = None,
    show_all: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--all", "-a", help="Follow every allocation and task of the job in one stream."
        ),
    ] = False,
    only_stdout: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--stdout", "-o", help="Show only the stdout stream."),
    ] = False,
    only_stderr: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--stderr", "-e", help="Show only the stderr stream."),
    ] = False,
    tail: Annotated[
        int | None,
        typer.Option("--tail", "-n", min=1, help="Show the last N lines, static (no follow)."),
    ] = None,
    export: Annotated[
        Path | None,
        typer.Option("--export", help="Write current logs to this file, then exit."),
    ] = None,
    include: Annotated[
        list[str] | None,
        typer.Option("--include", help="Show only lines matching this regex. Repeatable."),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option("--exclude", help="Hide lines matching this regex. Repeatable."),
    ] = None,
    highlight: Annotated[
        list[str] | None,
        typer.Option("--highlight", help="Highlight matches of this regex. Repeatable."),
    ] = None,
    verbose: VerboseOption = 0,
) -> None:
    """Stream a task's logs, or tail/export them.

    Defaults to the whole log, then a live stream of both stdout and stderr
    (interleaved) until the task stops or you press Ctrl-C. Pass --stdout or
    --stderr to show a single stream.
    Pass --all to follow every allocation and task of the job at once.
    """
    configure_verbosity(ctx, verbose)
    if show_all and export is not None:
        msg = EXPORT_WITH_ALL_ERROR
        raise typer.BadParameter(msg)
    # Compile first so a bad pattern is a usage error before anything is requested
    try:
        line_filter = LineFilter.compile(
            include=include or [], exclude=exclude or [], highlight=highlight or []
        )
    except InvalidPatternError as exc:
        raise typer.BadParameter(str(exc)) from exc
    streams = _streams(only_stdout=only_stdout, only_stderr=only_stderr)
    try:
        if show_all:
            asyncio.run(
                _run_all(
                    NomadConfig.resolve(),
                    job=job,
                    task=task,
                    streams=streams,
                    tail=tail,
                    line_filter=line_filter,
                )
            )
            return
        asyncio.run(
            _run(
                NomadConfig.resolve(),
                job=job,
                task=task,
                streams=streams,
                tail=tail,
                export_path=export,
                line_filter=line_filter,
            )
        )
    except KeyboardInterrupt:
        raise typer.Exit from None
