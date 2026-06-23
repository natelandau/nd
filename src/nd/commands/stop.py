"""The ``nd stop`` command: stop (and optionally purge) running Nomad jobs."""

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, cast

import typer
from nclutils import pp
from nclutils.ask import choose_multiple_from_list, choose_one_from_list
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table

from nd.constants import (
    POLL_INTERVAL_SECONDS,
    STOP_TIMEOUT_SECONDS,
    TERMINAL_ALLOC_STATUSES,
)
from nd.nomad import NomadClient, NomadConfig
from nd.nomad.errors import NomadError

if TYPE_CHECKING:
    from collections.abc import Callable

    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.job import JobListStub


class StopStatus(enum.StrEnum):
    """The terminal outcome of stopping a single job."""

    STOPPED = "stopped"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass(frozen=True)
class StopOutcome:
    """The result of stopping one job, ready for summary rendering."""

    job: JobListStub
    status: StopStatus
    detail: str = ""


@dataclass(frozen=True)
class TargetResolution:
    """The result of matching the optional job argument against running jobs."""

    candidates: list[JobListStub] = field(default_factory=list)
    needs_prompt: bool = False


@dataclass
class _JobRender:
    """Mutable per-job state backing one row of the live stop panel."""

    job: JobListStub
    started_at: float
    phase: str = "stopping"
    status: StopStatus | None = None
    ended_at: float | None = None


def resolve_targets(running: list[JobListStub], job_arg: str | None) -> TargetResolution:
    """Decide which running jobs a stop request targets.

    With no argument every running job is offered for a multi-select. With an
    argument, jobs whose name starts with it (case-insensitive) are matched: a
    single match is auto-selected, several matches are offered for a prompt, and
    no match yields no candidates.
    """
    if job_arg is None:
        return TargetResolution(candidates=running, needs_prompt=True)
    needle = job_arg.lower()
    matches = [job for job in running if job.name.lower().startswith(needle)]
    if len(matches) <= 1:
        return TargetResolution(candidates=matches, needs_prompt=False)
    return TargetResolution(candidates=matches, needs_prompt=True)


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
    total = len(outcomes)
    stopped = sum(1 for o in outcomes if o.status is StopStatus.STOPPED)
    secs = int(elapsed_seconds)
    count_part = _jobs_phrase(stopped) if stopped == total else f"{stopped} of {total} jobs"
    return f"Stopped {count_part} · {secs}s"


def _fmt_elapsed(seconds: float) -> str:
    """Format an elapsed duration as ``H:MM:SS``."""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


async def stop_and_wait(
    client: NomadClient,
    job: JobListStub,
    *,
    purge: bool,
    on_phase: Callable[[str], None],
) -> StopOutcome:
    """Stop one job and poll its allocations until they are terminal or time out.

    Reports phase text through ``on_phase`` for live rendering. Never raises: a
    Nomad failure becomes a ``FAILED`` outcome so a sibling job's progress is
    unaffected. The poll loop is bounded by a wall-clock deadline so a slow
    cluster cannot stretch the wait past ``STOP_TIMEOUT_SECONDS`` (the bound is on
    elapsed time, not on poll count, which would also charge for request latency).
    """
    try:
        on_phase("stopping")
        resp = await client.jobs.stop(job.id, purge=purge)
        pp.debug(
            f"DELETE /v1/job/{job.id}?purge={str(purge).lower()} -> eval {resp.eval_id or 'no-op'}"
        )
        pp.trace(
            f"deregister {job.id}: create_index={resp.eval_create_index} "
            f"modify_index={resp.job_modify_index}"
        )

        deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
        while True:
            start = time.perf_counter()
            allocs = await client.jobs.allocations(job.id)
            pending = sum(1 for a in allocs if a.client_status not in TERMINAL_ALLOC_STATUSES)
            elapsed_ms = (time.perf_counter() - start) * 1000
            pp.trace(
                f"GET /v1/job/{job.id}/allocations -> {len(allocs)} allocs "
                f"({pending} not terminal), {elapsed_ms:.0f}ms"
            )
            if all_allocs_terminal(allocs):
                return StopOutcome(job, StopStatus.STOPPED)
            if time.monotonic() >= deadline:
                return StopOutcome(job, StopStatus.TIMEOUT, "stop requested, still draining")
            on_phase(phase_text(allocs))
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except NomadError as exc:
        return StopOutcome(job, StopStatus.FAILED, str(exc))


@dataclass(frozen=True)
class _StatusDisplay:
    """How a terminal stop outcome reads in the panel: its glyph and row label."""

    glyph: str
    label: str


_STATUS_DISPLAY: dict[StopStatus, _StatusDisplay] = {
    StopStatus.STOPPED: _StatusDisplay("[green]✓[/]", "stopped"),
    StopStatus.TIMEOUT: _StatusDisplay("[yellow]⚠[/]", "still draining"),
    StopStatus.FAILED: _StatusDisplay("[red]✗[/]", "failed"),
}


def _outcome_phase(outcome: StopOutcome) -> str:
    """Map a terminal outcome to its row label."""
    return _STATUS_DISPLAY[outcome.status].label


def _titled_panel(table: Table, title: str) -> Panel:
    """Wrap a table in the stop command's left-titled cyan panel."""
    return Panel(table, title=title, title_align="left", border_style="cyan", expand=False)


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
    return _titled_panel(table, f"Would stop {_jobs_phrase(len(targets))}{suffix}")


def _render_dry_run(targets: list[JobListStub], *, purge: bool) -> None:
    """Print the dry-run panel describing what would be stopped."""
    pp.console().print(_build_dry_run_panel(targets, purge=purge))


def _clear_prompt_line(lines: int = 1) -> None:
    """Erase the residual questionary answer line(s) on an interactive terminal.

    A no-op off a terminal (pipes, tests) so control codes never leak into output.
    """
    console = pp.console()
    if not console.is_terminal:
        return
    console.file.write(f"\x1b[{lines}A\x1b[J")
    console.file.flush()


def _build_panel(rows: list[_JobRender], *, title: str, now: float) -> Panel:
    """Render the stop panel: a spinner for in-flight rows, a glyph for finished ones."""
    table = Table.grid(padding=(0, 2))
    table.add_column()  # status
    table.add_column()  # job name
    table.add_column()  # phase
    table.add_column(justify="right")  # elapsed
    for row in rows:
        status_cell = Spinner("dots") if row.status is None else _STATUS_DISPLAY[row.status].glyph
        ended = row.ended_at if row.ended_at is not None else now
        table.add_row(status_cell, row.job.name, row.phase, _fmt_elapsed(ended - row.started_at))
    return _titled_panel(table, title)


# allow_interspersed_args lets options follow the positional JOB (e.g. `nd stop web -p`);
# Typer groups disable that by default, which would parse `-p` as a subcommand.
app = typer.Typer(context_settings={"allow_interspersed_args": True})


@app.callback(invoke_without_command=True)
def stop(
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(help="Running job to stop; matches any job whose name starts with this."),
    ] = None,
    purge: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--purge", "-p", help="Garbage-collect the job after stopping."),
    ] = False,
    force: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--force", "-f", help="Skip the confirmation prompt."),
    ] = False,
    dry_run: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--dry-run", "-n", help="Resolve and report targets without stopping them."),
    ] = False,
    verbose: Annotated[
        int,
        typer.Option(
            "-v", "--verbose", count=True, help="Increase verbosity (-v debug, -vv trace)."
        ),
    ] = 0,
) -> None:
    """Stop (and optionally purge) one or more running Nomad jobs."""
    # Accept -v/-vv either before the command (root callback) or here; take the louder.
    verbose = max(getattr(ctx.obj, "verbose", 0), verbose)
    pp.configure(verbosity=verbose)
    exit_code = asyncio.run(_run(job_arg=job, purge=purge, force=force, dry_run=dry_run))
    if exit_code != 0:
        raise typer.Exit(exit_code)


async def _run(*, job_arg: str | None, purge: bool, force: bool, dry_run: bool) -> int:
    """Resolve targets, confirm, then stop them concurrently. Return the exit code.

    In ``dry_run`` mode every step runs except the stop call and the drain wait it
    triggers: the resolved targets are reported via ``pp.dryrun`` instead.
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

        resolution = resolve_targets(running, job_arg)
        targets = await _select_targets(resolution)
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

        outcomes = await _stop_all(client, targets, purge=purge)

    return exit_code_for(outcomes)


async def _select_targets(resolution: TargetResolution) -> list[JobListStub] | None:
    """Return the jobs to stop, prompting when several candidates need a choice.

    Returns None when the user cancels or selects nothing (caller exits 0). An
    empty list means an argument matched no jobs (caller reports and exits 1).
    """
    if not resolution.needs_prompt:
        return resolution.candidates
    choices = [(job.name, job) for job in resolution.candidates]
    # The overloaded prompt return does not narrow through asyncio.to_thread; cast it back.
    chosen = cast(
        "list[JobListStub] | None",
        await asyncio.to_thread(choose_multiple_from_list, choices, "Select jobs to stop"),
    )
    _clear_prompt_line()
    if not chosen:
        pp.info("Nothing selected")
        return None
    return chosen


async def _confirm(targets: list[JobListStub], *, purge: bool) -> bool:
    """Ask the user to confirm stopping the resolved jobs."""
    names = ", ".join(job.name for job in targets)
    verb = "Stop and PURGE" if purge else "Stop"
    answer = await asyncio.to_thread(
        choose_one_from_list,
        [("Yes", True), ("No", False)],
        f"{verb} {len(targets)} job(s): {names}?",
    )
    _clear_prompt_line()
    return bool(answer)


async def _stop_all(
    client: NomadClient, targets: list[JobListStub], *, purge: bool
) -> list[StopOutcome]:
    """Stop every target concurrently, rendering one live panel that ends final."""
    start = time.monotonic()
    rows = {job.id: _JobRender(job=job, started_at=start) for job in targets}
    stopping = stopping_title(len(targets), purge=purge)

    def panel(title: str) -> Panel:
        return _build_panel(list(rows.values()), title=title, now=time.monotonic())

    with Live(panel(stopping), console=pp.console(), refresh_per_second=12) as live:

        async def run_one(job: JobListStub) -> StopOutcome:
            def on_phase(text: str) -> None:
                rows[job.id].phase = text
                live.update(panel(stopping))

            outcome = await stop_and_wait(client, job, purge=purge, on_phase=on_phase)
            render = rows[job.id]
            render.status = outcome.status
            render.phase = _outcome_phase(outcome)
            render.ended_at = time.monotonic()
            live.update(panel(stopping))
            return outcome

        outcomes = list(await asyncio.gather(*(run_one(job) for job in targets)))
        live.update(panel(final_title(outcomes, elapsed_seconds=time.monotonic() - start)))

    # The live panel is transient on a pipe/CI; emit a durable line for any job
    # that did not stop cleanly so timeouts and failures are never silent.
    for outcome in outcomes:
        if outcome.status is StopStatus.TIMEOUT:
            pp.warning(f"{outcome.job.name}: {outcome.detail}")
        elif outcome.status is StopStatus.FAILED:
            pp.error(f"{outcome.job.name} failed to stop", details=[outcome.detail])
    return outcomes
