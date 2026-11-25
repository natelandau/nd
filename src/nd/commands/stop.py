"""The ``nd stop`` command: stop (and optionally purge) running Nomad jobs."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, Annotated

import typer
from nclutils import pp
from rich.table import Table

from nd.commands._common import (
    ForceOption,
    VerboseOption,
    command_app,
    configure_verbosity,
    dry_run_option,
)
from nd.commands._lifecycle import stop_and_wait
from nd.commands._orchestration import confirm_jobs, request_all, run_outcome_rows
from nd.nodes import node_names_by_id
from nd.nomad import NomadClient, NomadConfig
from nd.targets import select_targets
from nd.ui.panels import titled_panel
from nd.ui.prompts import FORCE_REMEDY, NAME_JOB_REMEDY
from nd.ui.text import plural

if TYPE_CHECKING:
    from rich.panel import Panel

    from nd.nomad.models.job import JobListStub


def stopping_title(count: int, *, purge: bool) -> str:
    """Build the panel title while jobs are stopping."""
    suffix = " (purge)" if purge else ""
    return f"Stopping {plural(count=count, noun='job')}{suffix}"


def _build_dry_run_panel(targets: list[JobListStub], *, purge: bool) -> Panel:
    """Build the static panel shown for a dry run (no spinners, dimmed rows)."""
    table = Table.grid(padding=(0, 2))
    table.add_column()
    table.add_column()
    action = "would stop and purge" if purge else "would stop"
    for job in targets:
        # Escape the leading bracket so Rich prints a literal "[dry-run]" tag, not markup.
        table.add_row(r"[dim]\[dry-run][/]", job.name, action)
    suffix = " (purge)" if purge else ""
    return titled_panel(table, f"Would stop {plural(count=len(targets), noun='job')}{suffix}")


app = command_app()


@app.callback(invoke_without_command=True)
def stop(  # noqa: PLR0913
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(
            help="Running job to stop; matches any job whose name contains this. "
            "Omit to pick from a list."
        ),
    ] = None,
    purge: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--purge", "-p", help="Garbage-collect the job after stopping."),
    ] = False,
    force: ForceOption = False,  # noqa: FBT002
    detach: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--detach", "-d", help="Request the stop and return without watching the drain."
        ),
    ] = False,
    no_shutdown_delay: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--no-shutdown-delay",
            "-S",
            help="Bypass the group/task shutdown delays for an immediate teardown.",
        ),
    ] = False,
    dry_run: Annotated[  # noqa: FBT002
        bool, dry_run_option("Resolve and report targets without stopping them.")
    ] = False,
    verbose: VerboseOption = 0,
) -> None:
    """Stop (and optionally purge) one or more running Nomad jobs.

    Confirms the targets (unless --force), stops each job, then watches its
    allocations drain to a terminal state. Use --purge to garbage-collect the job
    after it stops, --detach to return without watching the drain, and
    --no-shutdown-delay to skip the configured group and task shutdown delays.
    """
    configure_verbosity(ctx, verbose)
    exit_code = asyncio.run(
        _run(
            job_arg=job,
            purge=purge,
            force=force,
            detach=detach,
            no_shutdown_delay=no_shutdown_delay,
            dry_run=dry_run,
        )
    )
    if exit_code != 0:
        raise typer.Exit(exit_code)


async def _run(
    *,
    job_arg: str | None,
    purge: bool,
    force: bool,
    detach: bool,
    no_shutdown_delay: bool,
    dry_run: bool,
) -> int:
    """Resolve targets, confirm, then stop them concurrently. Return the exit code.

    In ``dry_run`` mode every step runs except the stop call and the drain wait it
    triggers: the resolved targets are reported in a dry-run panel instead. With
    ``detach`` the stop is requested for each target but the drain is not watched.
    """
    config = NomadConfig.resolve()
    pp.debug(
        "Resolved Nomad config",
        details=[f"address={config.address}", f"namespace={config.namespace}"],
    )
    async with NomadClient(config) as client:
        jobs = await client.jobs.list()
        running = [j for j in jobs if j.is_running]
        pp.debug(f"GET /v1/jobs -> {len(running)} running of {len(jobs)} jobs")
        if not running:
            pp.info("No running jobs to stop")
            return 0

        targets = await select_targets(
            running,
            job_arg,
            name_of=lambda j: j.name,
            prompt="Select jobs to stop",
            miss_noun="running job",
            remedy=NAME_JOB_REMEDY,
        )

        if not force and not await _confirm(targets, purge=purge):
            pp.info("Aborted")
            return 0

        if dry_run:
            pp.console().print(_build_dry_run_panel(targets, purge=purge))
            return 0

        if detach:
            return await _stop_detached(
                client, targets, purge=purge, no_shutdown_delay=no_shutdown_delay
            )

        node_names = await node_names_by_id(client)
        return await run_outcome_rows(
            targets,
            partial(
                stop_and_wait,
                client,
                purge=purge,
                no_shutdown_delay=no_shutdown_delay,
                node_names=node_names,
            ),
            label_of=lambda job: job.name,
            initial_phase="stopping",
            running_title=stopping_title(len(targets), purge=purge),
            done_verb="Stopped",
            fail_verb="stop",
        )


async def _stop_detached(
    client: NomadClient, targets: list[JobListStub], *, purge: bool, no_shutdown_delay: bool
) -> int:
    """Request the stop for every target concurrently and return without watching.

    Mirrors ``nomad job stop -detach``: each job is deregistered and the command
    returns immediately rather than polling allocations to terminal. A per-job Nomad
    failure is reported but does not abort the others. Returns 0 only when every stop
    request was accepted.
    """

    async def request_stop(job: JobListStub) -> str:
        await client.jobs.stop(job.id, purge=purge, no_shutdown_delay=no_shutdown_delay)
        return ""

    verb = "Requested stop and purge for" if purge else "Requested stop for"
    return await request_all(
        targets,
        request_stop,
        name_of=lambda job: job.name,
        summary_of=lambda count: f"{verb} {plural(count=count, noun='job')}",
        fail_verb="stop",
    )


async def _confirm(targets: list[JobListStub], *, purge: bool) -> bool:
    """Ask the user to confirm stopping the resolved jobs."""
    verb = "Stop and PURGE" if purge else "Stop"
    return await confirm_jobs([job.name for job in targets], verb=verb, remedy=FORCE_REMEDY)
