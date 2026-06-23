"""The ``nd logs`` command: stream, tail, or export a running task's logs."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import Annotated

import typer

from nd.commands._common import VerboseOption, configure_verbosity, run_alloc_action
from nd.nomad import NomadConfig

# allow_interspersed_args lets options follow the positional JOB (e.g. `nd logs web -e`).
app = typer.Typer(context_settings={"allow_interspersed_args": True})


def _streams(*, only_stdout: bool, only_stderr: bool) -> tuple[str, ...]:
    """Resolve the stream-selection flags to the streams to read (default both)."""
    if only_stdout and not only_stderr:
        return ("stdout",)
    if only_stderr and not only_stdout:
        return ("stderr",)
    return ("stdout", "stderr")


@app.callback(invoke_without_command=True)
def logs(  # noqa: PLR0913
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(help="Running job to read; matches any job whose name starts with this."),
    ] = None,
    task: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Target task; skips the task prompt."),
    ] = None,
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
        typer.Option("--tail", "-n", help="Show the last N lines, static (no follow)."),
    ] = None,
    export: Annotated[
        Path | None,
        typer.Option("--export", help="Write current logs to this file, then exit."),
    ] = None,
    verbose: VerboseOption = 0,
) -> None:
    """Stream a task's logs, or tail/export them.

    Defaults to a live stream of both stdout and stderr (interleaved) until
    interrupted with Ctrl-C. Pass --stdout or --stderr to show a single stream.
    """
    configure_verbosity(ctx, verbose)
    config = NomadConfig.resolve()
    streams = _streams(only_stdout=only_stdout, only_stderr=only_stderr)
    # running_only=False so logs of a dead, completed, or failed task stay reachable
    # (debugging a crash is the main reason to read logs).
    run_alloc_action(
        config,
        job=job,
        task=task,
        running_only=False,
        action=lambda nomad, alloc_id, task_name: nomad.stream_logs(
            alloc_id, task_name, streams=streams, tail=tail, export_path=export
        ),
    )
