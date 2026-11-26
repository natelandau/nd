"""The ``nd run`` command: deploy job files and watch the rollout live."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Annotated

import typer
from nclutils import pp

from nd.binary import NomadBinary, NomadBinaryError
from nd.commands._common import VerboseOption, command_app, configure_verbosity, dry_run_option
from nd.commands._deploy_failure import render_deploy_failure
from nd.commands._lifecycle import deploy_outcome, is_service_job, task_lifecycle, watch_deploy
from nd.commands._orchestration import (
    Severity,
    confirm_jobs,
    request_all,
    run_outcome_rows,
)
from nd.jobfiles import candidates_for, discover_job_files, load_job_directories
from nd.nodes import node_names_by_id
from nd.nomad import NomadClient, NomadConfig
from nd.nomad.errors import NomadError
from nd.targets import job_file_label, select_targets
from nd.ui.links import WebUi
from nd.ui.prompts import NAME_JOB_REMEDY, can_prompt

if TYPE_CHECKING:
    from nd.commands._lifecycle import DeployOutcome
    from nd.jobfiles import JobCandidate
    from nd.ui.live_panel import PanelUpdate

# The row label for a job whose rollout finished cleanly.
_DONE_LABEL = "deployed"


async def _cluster_job_states(client: NomadClient) -> tuple[set[str], set[str]]:
    """Return the ``(running, dead)`` job-name sets from the cluster's job list.

    ``run`` needs both halves from one fetch: running names are excluded from the
    deployable candidates, and dead names mark jobs a prior ``stop`` (without purge)
    left behind, which the user may want garbage-collected before deploying fresh.
    """
    jobs = await client.jobs.list()
    running = {j.name for j in jobs if j.is_running}
    dead = {j.name for j in jobs if j.status == "dead"}
    return running, dead


async def _maybe_purge_dead(
    client: NomadClient, dead_targets: list[JobCandidate], *, clean: bool
) -> None:
    """Garbage-collect dead jobs among the selected targets before deploying fresh.

    A ``stop`` without ``--purge`` leaves a job ``dead`` but still registered, so a
    following ``run`` layers the new version onto stale deployment history and the
    rollout view no longer reflects a clean start. When any selected target is present
    as a dead job, offer to purge it first: ``clean`` purges without asking, an
    interactive session prompts (default no), and a non-interactive session leaves the
    job untouched (deploy on top, unchanged behavior). A purge failure on one job is
    reported and skipped so the remaining jobs and the deploy still proceed.
    """
    if not dead_targets:
        return

    names = [t.name for t in dead_targets]
    if not clean:
        if not can_prompt():
            return
        if not await confirm_jobs(names, verb="Purge dead", remedy="pass --clean"):
            return

    async def purge_one(name: str) -> None:
        try:
            await client.jobs.stop(name, purge=True)
        except NomadError as exc:
            pp.warning(f"Could not purge dead job {name}", details=[str(exc)])
        else:
            pp.info(f"Purged dead job {name}")

    # Purges are independent per job, so fan them out and let each report itself.
    await asyncio.gather(*(purge_one(name) for name in names))


def _report_dry_run(targets: list[JobCandidate], *, dead: set[str], clean: bool) -> None:
    """Print what a real run would do for each target, calling out dead-job purges.

    A target already present as a dead job is only purged on a real run when ``clean``
    is set or the session is interactive, so the message for the plain dead case says
    "an interactive run" rather than promising a prompt a non-interactive run never shows.
    """
    for c in targets:
        if c.name in dead and clean:
            pp.dryrun(f"would purge dead job {c.name}, then run {c.name} ({c.file.path})")
        elif c.name in dead:
            pp.dryrun(
                f"would run {c.name} ({c.file.path}) on top of a dead job "
                "(an interactive run offers to purge it)"
            )
        else:
            pp.dryrun(f"would run {c.name} ({c.file.path})")


app = command_app()


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(
            help="Job to run; matches any not-running job whose name contains this. "
            "Omit to pick from a list."
        ),
    ] = None,
    detach: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--detach", "-d", help="Register the jobs and return without watching the rollout."
        ),
    ] = False,
    dry_run: Annotated[  # noqa: FBT002
        bool, dry_run_option("Resolve and validate without registering.")
    ] = False,
    clean: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--clean",
            "-c",
            help="Purge any selected job left dead by a prior stop before deploying, "
            "skipping the prompt.",
        ),
    ] = False,
    verbose: VerboseOption = 0,
) -> None:
    """Deploy one or more not-yet-running job files and watch them roll out.

    Only jobs that are not already running are offered; use plan to preview changes
    to a running job. Each selected file is validated, registered, and watched live:
    service jobs follow their deployment to success, while batch and system jobs
    follow their allocations. Use --detach to register and return without watching.
    If a selected job is still present in the cluster as a dead job (stopped without
    purge), you are offered to garbage-collect it first; --clean purges without asking.
    """
    configure_verbosity(ctx, verbose)
    exit_code = asyncio.run(_run(job_arg=job, detach=detach, dry_run=dry_run, clean=clean))
    if exit_code != 0:
        raise typer.Exit(exit_code)


async def _run(*, job_arg: str | None, detach: bool, dry_run: bool, clean: bool) -> int:
    """Resolve not-running candidates, validate, register, and watch the rollout.

    Returns the exit code: 0 on clean success, 1 on any failure. With ``detach`` the
    jobs are compiled and registered but the rollout is not watched.
    """
    files = discover_job_files(load_job_directories())
    config = NomadConfig.resolve()
    async with NomadClient(config) as client:
        running, dead = await _cluster_job_states(client)
        candidates = candidates_for(files, exclude_names=running)
        if not candidates:
            pp.info("No deployable job files (all known jobs are already running).")
            return 0

        targets = await select_targets(
            candidates,
            job_arg,
            name_of=lambda c: c.name,
            label_of=lambda c: job_file_label(name=c.name, path=c.file.path),
            prompt="Select jobs to run",
            miss_noun="not-running job file",
            remedy=NAME_JOB_REMEDY,
        )

        try:
            nomad = NomadBinary.create(config)
            await nomad.validate_all(c.file.path for c in targets)
        except NomadBinaryError as exc:
            pp.error(str(exc))
            return 1

        if dry_run:
            _report_dry_run(targets, dead=dead, clean=clean)
            return 0

        await _maybe_purge_dead(client, [t for t in targets if t.name in dead], clean=clean)

        if detach:
            return await _register_detached(client, targets, nomad)

        node_names = await node_names_by_id(client)
        return await run_outcome_rows(
            targets,
            partial(_deploy_one, client, node_names=node_names, nomad=nomad),
            label_of=lambda c: c.name,
            initial_phase="registering",
            running_title=f"Deploying {len(targets)} job(s)",
            done_verb="Deployed",
            fail_verb="deploy",
            explain_failure=partial(render_deploy_failure, ui=WebUi(config.ui_base)),
        )


async def _register_detached(
    client: NomadClient, targets: list[JobCandidate], nomad: NomadBinary
) -> int:
    """Compile and register every target concurrently, then return without watching.

    Mirrors ``nomad job run -detach``: each job file is compiled to JSON and
    registered, surfacing any register warnings, but the rollout is not polled. A
    per-job compile or register failure is reported and does not abort the others.
    Returns 0 only when every job registered successfully.
    """

    async def register(candidate: JobCandidate) -> str:
        body = await nomad.compile_job(candidate.file.path)
        return (await client.jobs.register(body)).warnings

    return await request_all(
        targets,
        register,
        name_of=lambda c: c.name,
        summary_of=lambda count: f"Registered {count} job(s)",
        fail_verb="register",
    )


async def _deploy_one(
    client: NomadClient,
    candidate: JobCandidate,
    update: PanelUpdate,
    *,
    node_names: dict[str, str],
    nomad: NomadBinary,
) -> DeployOutcome:
    """Compile, register, and watch one job to a terminal deploy state.

    Service jobs are watched via their deployment; batch/system jobs (which create
    no deployment) are watched via their allocations. Never raises: Nomad/binary
    failures become a failed outcome so a sibling job's progress is unaffected.

    Args:
        client: Authenticated Nomad client.
        candidate: The job file and name to deploy.
        update: Callback to update the live panel phase text and detail rows.
        node_names: Map of node ID to node name for the per-allocation detail rows.
        nomad: Configured `nomad` binary handle for the compile step.

    Returns:
        DeployOutcome: The terminal outcome for this candidate.
    """
    try:
        update("compiling")
        body = await nomad.compile_job(candidate.file.path)
        lifecycle = task_lifecycle(body)
        is_service = is_service_job(body)
        update("registering")
        resp = await client.jobs.register(body)
        outcome = await watch_deploy(
            client,
            candidate.name,
            node_names=node_names,
            lifecycle=lifecycle,
            update=update,
            done_label=_DONE_LABEL,
            is_service=is_service,
            since_index=resp.job_modify_index,
        )
        # Attach any register warnings so they are reported after the panel closes.
        return replace(outcome, warnings=resp.warnings)
    except (NomadBinaryError, NomadError) as exc:
        return deploy_outcome(
            candidate.name, Severity.FAIL, done_label=_DONE_LABEL, detail=str(exc)
        )
