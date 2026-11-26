"""The ``nd update`` command: recreate a running job from its local job file."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING, Annotated

import typer
from nclutils import pp

from nd.binary import NomadBinary, NomadBinaryError
from nd.commands._common import (
    ForceOption,
    VerboseOption,
    command_app,
    configure_verbosity,
    dry_run_option,
)
from nd.commands._deploy_failure import render_deploy_failure
from nd.commands._lifecycle import (
    DeployOutcome,
    deploy_outcome,
    is_service_job,
    stop_and_wait,
    task_lifecycle,
    watch_deploy,
)
from nd.commands._orchestration import Severity, confirm_jobs, run_outcome_rows
from nd.jobfiles import candidates_for, discover_job_files, load_job_directories
from nd.nodes import node_names_by_id
from nd.nomad import NomadClient, NomadConfig
from nd.nomad.errors import NomadError
from nd.targets import job_file_label, select_targets
from nd.ui.links import WebUi
from nd.ui.live_panel import LiveChild
from nd.ui.prompts import FORCE_REMEDY, NAME_JOB_REMEDY
from nd.ui.styles import muted
from nd.ui.text import plural

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nd.jobfiles import JobFile
    from nd.nomad.models.job import JobListStub
    from nd.ui.live_panel import PanelUpdate

# The row label for a job whose recreate finished cleanly.
_DONE_LABEL = "updated"


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


def _with_stopped_marker(update: PanelUpdate, *, drained: int) -> PanelUpdate:
    """Wrap ``update`` so every deploy-phase refresh keeps a stopped-version marker.

    The recreate reuses one row for both halves of the job's life: the deploy rows
    that arrive during the watch replace the drain rows the user just saw. Prepending
    a persistent summary line keeps the "previous version is down" beat on screen
    instead of letting it vanish. With ``drained`` of zero (nothing was running) there
    is nothing to report, so the original callback is returned unwrapped.
    """
    if drained <= 0:
        return update

    marker = LiveChild(
        cells=[muted(f"stopped previous version · {plural(count=drained, noun='alloc')} drained")]
    )

    def wrapped(phase: str, children: Sequence[LiveChild] = ()) -> None:
        update(phase, [marker, *children])

    return wrapped


async def _update_one(
    client: NomadClient,
    target: UpdateTarget,
    update: PanelUpdate,
    *,
    node_names: dict[str, str],
    nomad: NomadBinary,
    purge: bool,
) -> DeployOutcome:
    """Recreate one running job: compile, stop, re-register, and watch the rollout.

    The new spec is compiled (and thereby parsed) before the running job is stopped,
    so a bad file never tears down a healthy job. A drain that does not reach a
    terminal state aborts the recreate without re-registering; a re-register that
    fails after a clean stop is reported as the job being left down. Never raises:
    Nomad/binary failures become a terminal outcome so a sibling job is unaffected.

    Args:
        client: Authenticated Nomad client.
        target: The running job paired with its local file.
        update: Callback to update the live panel phase text and detail rows.
        node_names: Map of node ID to node name for the per-allocation detail rows.
        nomad: Configured ``nomad`` binary handle for the compile step.
        purge: Whether to garbage-collect the job after it drains.

    Returns:
        DeployOutcome: The terminal outcome for this target.
    """
    failed = partial(deploy_outcome, target.name, Severity.FAIL, done_label=_DONE_LABEL)
    try:
        update("compiling")
        body = await nomad.compile_job(target.file.path)
        lifecycle = task_lifecycle(body)
        is_service = is_service_job(body)
    except (NomadBinaryError, NomadError) as exc:
        return failed(detail=f"compile failed: {exc}")

    # Stop and watch the drain (and optional purge) before touching the new version.
    stopped = await stop_and_wait(
        client, target.job, update=update, purge=purge, node_names=node_names
    )
    if not stopped.workload_stopped:
        # The job is still draining or the stop errored; leaving it untouched is safer
        # than re-registering on top of a job that has not come down.
        reason = "timeout" if stopped.severity is Severity.WARN else "failed"
        return DeployOutcome(
            name=target.name,
            severity=stopped.severity,
            label=stopped.label,
            detail=f"not re-deployed (stop {reason}): {stopped.detail}",
        )

    # Keep a durable marker for the just-completed drain so the deploy rows that
    # replace the drain rows do not erase the "previous version is down" beat.
    deploy_update = _with_stopped_marker(update, drained=stopped.drained)

    try:
        deploy_update("registering")
        resp = await client.jobs.register(body)
    except NomadError as exc:
        # The old version is already gone here, so call out that the job is down.
        return failed(detail=f"stopped but re-deploy failed: {exc}")

    try:
        outcome = await watch_deploy(
            client,
            target.name,
            node_names=node_names,
            lifecycle=lifecycle,
            update=deploy_update,
            done_label=_DONE_LABEL,
            is_service=is_service,
            since_index=resp.job_modify_index,
        )
    except NomadError as exc:
        # watch_deploy polls the cluster, so a transient error here would otherwise
        # escape and crash the concurrent panel, killing every sibling job's watch.
        # The job is already registered, so report the watch failure rather than raise.
        return failed(detail=f"re-registered but watch failed: {exc}")
    return replace(outcome, warnings=resp.warnings)


app = command_app()


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
    force: ForceOption = False,  # noqa: FBT002
    dry_run: Annotated[  # noqa: FBT002
        bool, dry_run_option("Resolve and validate without recreating.")
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


async def _run(*, job_arg: str | None, no_purge: bool, force: bool, dry_run: bool) -> int:
    """Resolve running targets with local files, confirm, then recreate them.

    Returns the exit code: 0 on clean success, 1 on any failure. The new spec for
    every target is validated up front, before any job is stopped.
    """
    files = discover_job_files(load_job_directories())
    config = NomadConfig.resolve()
    async with NomadClient(config) as client:
        jobs = await client.jobs.list()
        running = [j for j in jobs if j.is_running]
        targets_all = build_update_targets(files, running)
        if not targets_all:
            pp.info("No running jobs have a local job file to update.")
            return 0

        targets = await select_targets(
            targets_all,
            job_arg,
            name_of=lambda t: t.name,
            label_of=lambda t: job_file_label(name=t.name, path=t.file.path),
            prompt="Select jobs to update",
            miss_noun="running job with a local file",
            remedy=NAME_JOB_REMEDY,
        )

        purge = not no_purge
        if not force and not await _confirm(targets, purge=purge):
            pp.info("Aborted")
            return 0

        try:
            nomad = NomadBinary.create(config)
            await nomad.validate_all(t.file.path for t in targets)
        except NomadBinaryError as exc:
            pp.error(str(exc))
            return 1

        if dry_run:
            for t in targets:
                pp.dryrun(f"would recreate {t.name} ({t.file.path})")
            return 0

        node_names = await node_names_by_id(client)
        return await run_outcome_rows(
            targets,
            partial(_update_one, client, node_names=node_names, nomad=nomad, purge=purge),
            label_of=lambda t: t.name,
            initial_phase="compiling",
            running_title=f"Updating {len(targets)} job(s)",
            done_verb="Updated",
            fail_verb="update",
            explain_failure=partial(render_deploy_failure, ui=WebUi(config.ui_base)),
        )


async def _confirm(targets: list[UpdateTarget], *, purge: bool) -> bool:
    """Ask the user to confirm recreating the resolved jobs."""
    verb = "Stop, PURGE and re-deploy" if purge else "Stop and re-deploy"
    return await confirm_jobs([t.name for t in targets], verb=verb, remedy=FORCE_REMEDY)
