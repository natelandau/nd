"""The ``nd stop`` command: stop (and optionally purge) running Nomad jobs."""

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

import typer
from nclutils import pp
from rich.table import Table

from nd.commands._common import VerboseOption, configure_verbosity
from nd.constants import (
    POLL_INTERVAL_SECONDS,
    STOP_TIMEOUT_SECONDS,
    TERMINAL_ALLOC_STATUSES,
)
from nd.nomad import NomadClient, NomadConfig
from nd.nomad.errors import NomadDecodeError, NomadError
from nd.targets import resolve_targets, select_candidates
from nd.ui.alloc_rows import alloc_children
from nd.ui.duration import summary_title
from nd.ui.live_panel import PanelUpdate, run_rows
from nd.ui.panels import titled_panel
from nd.ui.prompts import select_one
from nd.ui.styles import OUTCOME_GLYPH

if TYPE_CHECKING:
    from rich.panel import Panel

    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.job import JobListStub


class StopStatus(enum.StrEnum):
    """The terminal outcome of stopping a single job."""

    STOPPED = "stopped"
    TIMEOUT = "timeout"
    FAILED = "failed"
    PURGE_FAILED = "purge_failed"


@dataclass(frozen=True)
class StopOutcome:
    """The result of stopping one job, ready for summary rendering."""

    job: JobListStub
    status: StopStatus
    detail: str = ""


# Maps each terminal stop status to its outcome glyph and row label. Each label
# carries its glyph's color so the status word reads as success/failure on its own.
_OUTCOME_ROW: dict[StopStatus, tuple[str, str]] = {
    StopStatus.STOPPED: (OUTCOME_GLYPH["ok"], "[green]stopped[/]"),
    StopStatus.TIMEOUT: (OUTCOME_GLYPH["warn"], "[yellow]still draining[/]"),
    StopStatus.FAILED: (OUTCOME_GLYPH["fail"], "[red]failed[/]"),
    # The workload did stop; only the follow-up garbage-collection failed, so this
    # warns rather than reading as a hard "failed to stop".
    StopStatus.PURGE_FAILED: (OUTCOME_GLYPH["warn"], "[yellow]stopped, purge failed[/]"),
}


def all_allocs_terminal(allocs: list[AllocListStub]) -> bool:
    """Return True when every allocation has reached a terminal client status."""
    return all(alloc.client_status in TERMINAL_ALLOC_STATUSES for alloc in allocs)


def exit_code_for(outcomes: list[StopOutcome]) -> int:
    """Return 0 only when every job stopped cleanly, otherwise 1."""
    return 0 if all(o.status is StopStatus.STOPPED for o in outcomes) else 1


def running_task_names(allocs: list[AllocListStub]) -> list[str]:
    """Return the sorted, unique names of tasks currently in the running state.

    During a stop the main tasks die first and post-stop lifecycle tasks run
    afterward, so the still-running set surfaces the post-stop / cleanup tasks.
    """
    names = {
        name
        for alloc in allocs
        for name, state in alloc.task_states.items()
        if state.state == "running"
    }
    return sorted(names)


def phase_text(allocs: list[AllocListStub]) -> str:
    """Build the live phase label for a draining job."""
    if not allocs:
        return "stopping"
    names = running_task_names(allocs)
    if names:
        return "running: " + ", ".join(names)
    pending = sum(1 for a in allocs if a.client_status not in TERMINAL_ALLOC_STATUSES)
    return f"draining {pending} allocs" if pending else "stopping"


def _jobs_phrase(count: int) -> str:
    """Render a job count with the correctly pluralized noun (``1 job``/``2 jobs``)."""
    return f"{count} job{'s' if count != 1 else ''}"


def stopping_title(count: int, *, purge: bool) -> str:
    """Build the panel title while jobs are stopping."""
    suffix = " (purge)" if purge else ""
    return f"Stopping {_jobs_phrase(count)}{suffix}"


def final_title(outcomes: list[StopOutcome], *, elapsed_seconds: float) -> str:
    """Build the panel title for the final frame, with totals and elapsed time."""
    stopped = sum(1 for o in outcomes if o.status is StopStatus.STOPPED)
    return summary_title("Stopped", stopped, len(outcomes), elapsed_seconds)


async def stop_and_wait(
    client: NomadClient,
    job: JobListStub,
    *,
    purge: bool,
    no_shutdown_delay: bool = False,
    node_names: dict[str, str],
    update: PanelUpdate,
) -> StopOutcome:
    """Stop one job and poll its allocations until they are terminal or time out.

    Reports drain progress through ``update``: a phase summary plus a detail row
    per allocation and task (so post-stop tasks draining on each node are visible).
    When ``purge`` is set the job is garbage-collected only after the drain reaches a
    terminal state, so the post-stop tasks are watched first; a timed-out or failed
    drain leaves the job queryable for inspection rather than purging it.
    Never raises: a Nomad failure becomes a ``FAILED`` outcome so a sibling job's
    progress is unaffected. The poll loop is bounded by a wall-clock deadline so a
    slow cluster cannot stretch the wait past ``STOP_TIMEOUT_SECONDS`` (the bound is
    on elapsed time, not on poll count, which would also charge for request latency).
    """
    try:
        update("stopping")
        # Stop without purging so the job stays queryable while its allocations (and any
        # post-stop tasks) drain. A purge here deregisters the job immediately, leaving the
        # allocations endpoint empty so the drain goes unwatched; the dead job is purged in
        # _purge_dead_job below, only after it is confirmed terminal.
        resp = await client.jobs.stop(job.id, purge=False, no_shutdown_delay=no_shutdown_delay)
        pp.debug(f"DELETE /v1/job/{job.id}?purge=false -> eval {resp.eval_id or 'no-op'}")
        pp.trace(
            f"deregister {job.id}: create_index={resp.eval_create_index} "
            f"modify_index={resp.job_modify_index}"
        )

        deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
        while True:
            try:
                start = time.perf_counter()
                allocs = await client.jobs.allocations(job.id)
            except NomadDecodeError as exc:
                # A post-stop/cleanup task that just (re)started can momentarily
                # serialize in a shape we cannot decode; skip this tick and retry
                # rather than reporting the stop as failed. The deadline below is
                # the backstop if it never recovers.
                pp.debug(f"{job.id}: skipping drain poll after transient decode error: {exc}")
            else:
                pending = sum(1 for a in allocs if a.client_status not in TERMINAL_ALLOC_STATUSES)
                elapsed_ms = (time.perf_counter() - start) * 1000
                pp.trace(
                    f"GET /v1/job/{job.id}/allocations -> {len(allocs)} allocs "
                    f"({pending} not terminal), {elapsed_ms:.0f}ms"
                )
                if all_allocs_terminal(allocs):
                    if purge:
                        return await _purge_dead_job(client, job, update=update)
                    return StopOutcome(job, StopStatus.STOPPED)
                update(phase_text(allocs), alloc_children(allocs, node_names, None))
            if time.monotonic() >= deadline:
                return StopOutcome(job, StopStatus.TIMEOUT, "stop requested, still draining")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except NomadError as exc:
        return StopOutcome(job, StopStatus.FAILED, str(exc))


async def _purge_dead_job(
    client: NomadClient, job: JobListStub, *, update: PanelUpdate
) -> StopOutcome:
    """Garbage-collect a job that has already drained to a terminal state.

    Nomad has no per-job GC endpoint other than the purging deregister, so a clean
    stop is purged by re-issuing the deregister with ``purge=true`` once the drain has
    been watched to completion. ``no_shutdown_delay`` is not forwarded: the job is
    already dead here, so there are no live allocations for the flag to act on. A purge
    failure becomes a ``PURGE_FAILED`` outcome (the workload stopped but was not
    collected) so it is reported as a warning rather than a hard "failed to stop".
    """
    try:
        update("purging")
        await client.jobs.stop(job.id, purge=True)
        pp.debug(f"DELETE /v1/job/{job.id}?purge=true -> garbage-collected dead job")
    except NomadError as exc:
        return StopOutcome(job, StopStatus.PURGE_FAILED, f"stopped but purge failed: {exc}")
    return StopOutcome(job, StopStatus.STOPPED)


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
    return titled_panel(table, f"Would stop {_jobs_phrase(len(targets))}{suffix}")


def _render_dry_run(targets: list[JobListStub], *, purge: bool) -> None:
    """Print the dry-run panel describing what would be stopped."""
    pp.console().print(_build_dry_run_panel(targets, purge=purge))


# allow_interspersed_args lets options follow the positional JOB (e.g. `nd stop web -p`);
# Typer groups disable that by default, which would parse `-p` as a subcommand.
app = typer.Typer(context_settings={"allow_interspersed_args": True})


@app.callback(invoke_without_command=True)
def stop(  # noqa: PLR0913
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(
            help="Running job to stop; matches any job whose name starts with this. "
            "Omit to pick from a list."
        ),
    ] = None,
    purge: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--purge", "-p", help="Garbage-collect the job after stopping."),
    ] = False,
    force: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--force", "-f", help="Skip the confirmation prompt."),
    ] = False,
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
        bool,
        typer.Option("--dry-run", "-n", help="Resolve and report targets without stopping them."),
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


async def _run(  # noqa: PLR0911
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
    triggers: the resolved targets are reported via ``pp.dryrun`` instead. With
    ``detach`` the stop is requested for each target but the drain is not watched.
    """
    config = NomadConfig.resolve()
    pp.debug(
        "Resolved Nomad config",
        details=[f"address={config.address}", f"namespace={config.namespace}"],
    )
    async with NomadClient.from_config(config) as client:
        jobs = await client.jobs.list()
        running = [j for j in jobs if j.status == "running"]
        pp.debug(f"GET /v1/jobs -> {len(running)} running of {len(jobs)} jobs")
        if not running:
            pp.info("No running jobs to stop")
            return 0

        resolution = resolve_targets(running, job_arg, name_of=lambda j: j.name)
        targets = await select_candidates(
            resolution, "Select jobs to stop", label_of=lambda j: j.name
        )
        if targets is None:
            return 0  # nothing selected; already reported
        if not targets:
            pp.error(f"No running job matching '{job_arg}'")
            return 1

        if not force and not await _confirm(targets, purge=purge):
            pp.info("Aborted")
            return 0

        if dry_run:
            _render_dry_run(targets, purge=purge)
            return 0

        if detach:
            return await _stop_detached(
                client, targets, purge=purge, no_shutdown_delay=no_shutdown_delay
            )

        outcomes = await _stop_all(
            client, targets, purge=purge, no_shutdown_delay=no_shutdown_delay
        )

    return exit_code_for(outcomes)


async def _stop_detached(
    client: NomadClient, targets: list[JobListStub], *, purge: bool, no_shutdown_delay: bool
) -> int:
    """Request the stop for every target concurrently and return without watching.

    Mirrors ``nomad job stop -detach``: each job is deregistered and the command
    returns immediately rather than polling allocations to terminal. A per-job Nomad
    failure is reported but does not abort the others. Returns 0 only when every stop
    request was accepted.
    """

    async def issue(job: JobListStub) -> tuple[JobListStub, str | None]:
        try:
            await client.jobs.stop(job.id, purge=purge, no_shutdown_delay=no_shutdown_delay)
        except NomadError as exc:
            return (job, str(exc))
        return (job, None)

    results = await asyncio.gather(*(issue(job) for job in targets))
    requested = [job for job, err in results if err is None]
    failed = [(job, err) for job, err in results if err is not None]
    if requested:
        verb = "Requested stop and purge for" if purge else "Requested stop for"
        pp.success(f"{verb} {_jobs_phrase(len(requested))}", details=[j.name for j in requested])
    for job, err in failed:
        pp.error(f"{job.name} failed to stop", details=[err])
    return 0 if not failed else 1


async def _confirm(targets: list[JobListStub], *, purge: bool) -> bool:
    """Ask the user to confirm stopping the resolved jobs."""
    names = ", ".join(job.name for job in targets)
    verb = "Stop and PURGE" if purge else "Stop"
    answer = await select_one(
        [("Yes", True), ("No", False)],
        f"{verb} {len(targets)} job(s): {names}?",
    )
    return bool(answer)


async def _stop_all(
    client: NomadClient, targets: list[JobListStub], *, purge: bool, no_shutdown_delay: bool
) -> list[StopOutcome]:
    """Stop every target concurrently, rendering one live panel that ends final."""
    # Resolve node IDs to names once so each job's detail rows can show placement.
    node_names = {node.id: node.name for node in await client.nodes.list()}

    async def do_work(job: JobListStub, update: PanelUpdate) -> StopOutcome:
        return await stop_and_wait(
            client,
            job,
            purge=purge,
            no_shutdown_delay=no_shutdown_delay,
            node_names=node_names,
            update=update,
        )

    ordered = await run_rows(
        targets,
        do_work,
        label_of=lambda job: job.name,
        initial_phase="stopping",
        finish_of=lambda o: _OUTCOME_ROW[o.status],
        running_title=stopping_title(len(targets), purge=purge),
        final_title=lambda outcomes, secs: final_title(outcomes, elapsed_seconds=secs),
    )

    # The live panel is transient on a pipe/CI; emit a durable line for any job
    # that did not stop cleanly so timeouts and failures are never silent.
    for outcome in ordered:
        if outcome.status in (StopStatus.TIMEOUT, StopStatus.PURGE_FAILED):
            pp.warning(f"{outcome.job.name}: {outcome.detail}")
        elif outcome.status is StopStatus.FAILED:
            pp.error(f"{outcome.job.name} failed to stop", details=[outcome.detail])
    return ordered
