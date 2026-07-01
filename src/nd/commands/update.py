"""The ``nd update`` command: recreate a running job from its local job file."""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

import typer
from nclutils import pp

from nd.binary import NomadBinary, NomadBinaryError
from nd.commands._common import VerboseOption, configure_verbosity
from nd.commands._orchestration import (
    confirm_jobs,
    fail_row,
    final_panel_title,
    node_names_by_id,
    ok_row,
    report_outcomes,
    warn_row,
)
from nd.commands.run import DeployStatus, task_lifecycle, watch_deploy
from nd.commands.stop import StopStatus, stop_and_wait
from nd.jobfiles import candidates_for, discover_job_files, load_job_directories
from nd.nomad import NomadClient, NomadConfig
from nd.nomad.errors import NomadError
from nd.targets import resolve_targets, select_candidates
from nd.ui.live_panel import PanelUpdate, run_rows

if TYPE_CHECKING:
    from nd.jobfiles import JobFile
    from nd.nomad.models.job import JobListStub


@dataclass(frozen=True)
class UpdateTarget:
    """A running job paired with the local file that declares it.

    Carries both halves the recreate needs: the ``file`` to compile and register,
    and the running ``job`` stub to stop and drain.
    """

    name: str
    file: JobFile
    job: JobListStub


def build_update_targets(files: list[JobFile], running: list[JobListStub]) -> list[UpdateTarget]:
    """Pair each declared job that is currently running with its local file.

    A job running in the cluster with no local file cannot be updated (there is no
    spec to re-register), and a local job that is not running is a ``run``, not an
    update, so both are omitted.

    Args:
        files: Discovered local job files and the names each declares.
        running: The jobs currently running in the cluster.

    Returns:
        One target per declared job name that is also running.
    """
    by_name = {job.name: job for job in running}
    targets: list[UpdateTarget] = []
    for candidate in candidates_for(files):
        job = by_name.get(candidate.name)
        if job is not None:
            targets.append(UpdateTarget(name=candidate.name, file=candidate.file, job=job))
    return targets


class UpdateStatus(enum.StrEnum):
    """The terminal outcome of recreating one job."""

    UPDATED = "updated"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class UpdateOutcome:
    """The result of recreating one job, ready for summary rendering."""

    name: str
    status: UpdateStatus
    detail: str = ""
    warnings: str = ""


# Outcome labels carry their glyph's color so the status word reads on its own.
_OUTCOME_ROW: dict[UpdateStatus, tuple[str, str]] = {
    UpdateStatus.UPDATED: ok_row("updated"),
    UpdateStatus.FAILED: fail_row("failed"),
    UpdateStatus.TIMEOUT: warn_row("still deploying"),
}

# Map the deploy watch's terminal status onto the update outcome.
_DEPLOY_TO_UPDATE: dict[DeployStatus, UpdateStatus] = {
    DeployStatus.DEPLOYED: UpdateStatus.UPDATED,
    DeployStatus.FAILED: UpdateStatus.FAILED,
    DeployStatus.TIMEOUT: UpdateStatus.TIMEOUT,
}

# Stop outcomes that mean the workload reached a terminal state, so the recreate
# may safely re-register. A drain that timed out or errored must not be re-run.
_STOP_PROCEED = frozenset({StopStatus.STOPPED, StopStatus.PURGE_FAILED})


async def _update_one(
    client: NomadClient,
    target: UpdateTarget,
    *,
    node_names: dict[str, str],
    update: PanelUpdate,
    nomad: NomadBinary,
    purge: bool,
) -> UpdateOutcome:
    """Recreate one running job: compile, stop, re-register, and watch the rollout.

    The new spec is compiled (and thereby parsed) before the running job is stopped,
    so a bad file never tears down a healthy job. A drain that does not reach a
    terminal state aborts the recreate without re-registering; a re-register that
    fails after a clean stop is reported as the job being left down. Never raises:
    Nomad/binary failures become a terminal outcome so a sibling job is unaffected.

    Args:
        client: Authenticated Nomad client.
        target: The running job paired with its local file.
        node_names: Map of node ID to node name for the per-allocation detail rows.
        update: Callback to update the live panel phase text and detail rows.
        nomad: Configured ``nomad`` binary handle for the compile step.
        purge: Whether to garbage-collect the job after it drains.

    Returns:
        The terminal outcome for this target.
    """
    try:
        update("compiling")
        # compile_to_json shells out to the nomad binary (blocking); run it off the
        # event loop so sibling recreates keep making progress concurrently.
        body = await asyncio.to_thread(nomad.compile_to_json, target.file.path)
        lifecycle = task_lifecycle(body)
    except NomadBinaryError as exc:
        return UpdateOutcome(target.name, UpdateStatus.FAILED, f"compile failed: {exc}")

    # Stop and watch the drain (and optional purge) before touching the new version.
    stop_outcome = await stop_and_wait(
        client, target.job, purge=purge, node_names=node_names, update=update
    )
    if stop_outcome.status not in _STOP_PROCEED:
        # The job is still draining or the stop errored; leaving it untouched is safer
        # than re-registering on top of a job that has not come down.
        status = (
            UpdateStatus.TIMEOUT
            if stop_outcome.status is StopStatus.TIMEOUT
            else UpdateStatus.FAILED
        )
        return UpdateOutcome(
            target.name,
            status,
            f"not re-deployed (stop {stop_outcome.status}): {stop_outcome.detail}",
        )

    try:
        update("registering")
        resp = await client.jobs.register(body)
    except NomadError as exc:
        # The old version is already gone here, so call out that the job is down.
        return UpdateOutcome(
            target.name, UpdateStatus.FAILED, f"stopped but re-deploy failed: {exc}"
        )

    try:
        outcome = await watch_deploy(
            client,
            target.name,
            node_names=node_names,
            lifecycle=lifecycle,
            update=update,
            since_index=resp.job_modify_index,
        )
    except NomadError as exc:
        # watch_deploy polls the cluster, so a transient error here would otherwise
        # escape and crash the concurrent panel, killing every sibling job's watch.
        # The job is already registered, so report the watch failure rather than raise.
        return UpdateOutcome(
            target.name, UpdateStatus.FAILED, f"re-registered but watch failed: {exc}"
        )
    return UpdateOutcome(
        target.name, _DEPLOY_TO_UPDATE[outcome.status], outcome.detail, warnings=resp.warnings
    )


# allow_interspersed_args lets options follow the positional JOB argument; Typer
# groups disable that by default, which would parse flags as subcommands.
app = typer.Typer(context_settings={"allow_interspersed_args": True})


@app.callback(invoke_without_command=True)
def update(
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(
            help="Running job to update; matches any running job whose name contains "
            "this and has a local file. Omit to pick from a list."
        ),
    ] = None,
    no_purge: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--no-purge",
            help="Stop without garbage-collecting the job (keeps its version history).",
        ),
    ] = False,
    force: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--force", "-f", help="Skip the confirmation prompt."),
    ] = False,
    dry_run: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--dry-run", "-n", help="Resolve and validate without recreating."),
    ] = False,
    verbose: VerboseOption = 0,
) -> None:
    """Recreate one or more running jobs from their local job files.

    Each selected job is compiled and validated, then stopped, drained, purged (unless
    --no-purge), re-registered, and watched to a terminal deploy state. Use this to
    roll out a changed job file or to force a fresh version (e.g. re-pull a docker
    image); whether an image is actually re-pulled depends on the job's docker driver
    config (force_pull), not on nd.
    """
    configure_verbosity(ctx, verbose)
    exit_code = asyncio.run(_run(job_arg=job, no_purge=no_purge, force=force, dry_run=dry_run))
    if exit_code != 0:
        raise typer.Exit(exit_code)


async def _run(*, job_arg: str | None, no_purge: bool, force: bool, dry_run: bool) -> int:  # noqa: PLR0911
    """Resolve running targets with local files, confirm, then recreate them.

    Returns the exit code: 0 on clean success, 1 on any failure. The new spec for
    every target is validated up front, before any job is stopped.
    """
    files = discover_job_files(load_job_directories())
    config = NomadConfig.resolve()
    async with NomadClient.from_config(config) as client:
        jobs = await client.jobs.list()
        running = [j for j in jobs if j.status == "running"]
        targets_all = build_update_targets(files, running)
        if not targets_all:
            pp.info("No running jobs have a local job file to update.")
            return 0

        resolution = resolve_targets(targets_all, job_arg, name_of=lambda t: t.name)
        targets = await select_candidates(
            resolution,
            "Select jobs to update",
            label_of=lambda t: f"{t.name}  [{t.file.path.name}]",
        )
        if targets is None:
            return 0
        if not targets:
            pp.error(f"No running job with a local file matching '{job_arg}'")
            return 1

        purge = not no_purge
        if not force and not await _confirm(targets, purge=purge):
            pp.info("Aborted")
            return 0

        try:
            nomad = NomadBinary.create(config)
            # dict.fromkeys dedups so a multi-job file is validated once.
            for path in dict.fromkeys(t.file.path for t in targets):
                nomad.validate(path)
        except NomadBinaryError as exc:
            pp.error(str(exc))
            return 1

        if dry_run:
            for t in targets:
                pp.dryrun(f"would recreate {t.name} ({t.file.path})")
            return 0

        outcomes = await _update_all(client, targets, nomad, purge=purge)

    return 0 if all(o.status is UpdateStatus.UPDATED for o in outcomes) else 1


async def _confirm(targets: list[UpdateTarget], *, purge: bool) -> bool:
    """Ask the user to confirm recreating the resolved jobs."""
    verb = "Stop, PURGE and re-deploy" if purge else "Stop and re-deploy"
    return await confirm_jobs([t.name for t in targets], verb=verb)


async def _update_all(
    client: NomadClient, targets: list[UpdateTarget], nomad: NomadBinary, *, purge: bool
) -> list[UpdateOutcome]:
    """Recreate every target concurrently under one live panel.

    Args:
        client: Authenticated Nomad client.
        targets: The running jobs to recreate.
        nomad: Configured ``nomad`` binary handle for the compile step.
        purge: Whether to garbage-collect each job after it drains.

    Returns:
        Ordered list of outcomes, one per target.
    """
    # Resolve node IDs to names once so every job's detail rows can show placement.
    node_names = await node_names_by_id(client)

    async def do_work(target: UpdateTarget, update: PanelUpdate) -> UpdateOutcome:
        return await _update_one(
            client, target, node_names=node_names, update=update, nomad=nomad, purge=purge
        )

    ordered = await run_rows(
        targets,
        do_work,
        label_of=lambda t: t.name,
        initial_phase="compiling",
        finish_of=lambda o: _OUTCOME_ROW[o.status],
        running_title=f"Updating {len(targets)} job(s)",
        final_title=_final_title,
    )

    # The live panel is transient on a pipe/CI; emit a durable line for anything that
    # did not update cleanly so timeouts and a left-down job are never silent.
    report_outcomes(
        ordered,
        name_of=lambda o: o.name,
        detail_of=lambda o: o.detail,
        is_warn=lambda o: o.status is UpdateStatus.TIMEOUT,
        is_fail=lambda o: o.status is UpdateStatus.FAILED,
        fail_verb="update",
        warn_fallback="still deploying",
        warnings_of=lambda o: o.warnings,
    )
    return ordered


def _final_title(outcomes: list[UpdateOutcome], elapsed_seconds: float) -> str:
    """Build the final panel title with updated totals and elapsed seconds."""
    return final_panel_title(
        outcomes,
        elapsed_seconds,
        verb="Updated",
        succeeded=lambda o: o.status is UpdateStatus.UPDATED,
    )
