"""The ``nd run`` command: deploy job files and watch the rollout live."""

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Annotated

import msgspec
import typer
from nclutils import pp

from nd.binary import NomadBinary, NomadBinaryError
from nd.commands._common import VerboseOption, configure_verbosity
from nd.commands._orchestration import (
    fail_row,
    final_panel_title,
    node_names_by_id,
    ok_row,
    report_outcomes,
    warn_row,
)
from nd.constants import DEPLOY_TIMEOUT_SECONDS, HEALTHY_ALLOC_STATUSES, POLL_INTERVAL_SECONDS
from nd.jobfiles import candidates_for, discover_job_files, load_job_directories
from nd.nomad import NomadClient, NomadConfig
from nd.nomad.errors import NomadDecodeError, NomadError
from nd.targets import resolve_targets, select_candidates
from nd.ui.alloc_rows import alloc_children
from nd.ui.live_panel import PanelUpdate, run_rows

if TYPE_CHECKING:
    from nd.jobfiles import JobCandidate
    from nd.nomad.models.deployment import Deployment
    from nd.ui.alloc_rows import TaskLifecycle

# Deployment statuses that mean the rollout is finished, one way or the other.
_DEPLOY_SUCCESS = "successful"
_DEPLOY_FAILURE = frozenset({"failed", "cancelled"})


class DeployStatus(enum.StrEnum):
    """The terminal outcome of deploying one job."""

    DEPLOYED = "deployed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class DeployOutcome:
    """The result of deploying one job, ready for summary rendering."""

    name: str
    status: DeployStatus
    detail: str = ""
    warnings: str = ""


def deploy_phase(dep: Deployment) -> str:
    """Summarize a deployment's progress as ``<status>: <healthy>/<desired> healthy``.

    Aggregates counts across all task groups so the live panel shows a single
    meaningful number rather than per-group noise.
    """
    healthy = sum(tg.healthy_allocs for tg in dep.task_groups.values())
    desired = sum(tg.desired_total for tg in dep.task_groups.values())
    return f"{dep.status}: {healthy}/{desired} healthy"


def task_lifecycle(body: bytes) -> TaskLifecycle:
    """Parse task lifecycle order and labels from a compiled job spec.

    Tasks are ordered prestart, then main, then poststart/sidecar within each
    group, so the panel shows them in the order Nomad runs them. Poststop tasks are
    omitted because they only run when an allocation stops, not during a deploy.

    Args:
        body: The compiled ``{"Job": {...}}`` JSON from ``nomad job run -output``.

    Returns:
        A map of group name to ``{task name: (sort order, label)}``.
    """
    job = msgspec.json.decode(body).get("Job") or {}
    lifecycle: TaskLifecycle = {}
    for group in job.get("TaskGroups") or []:
        tasks: dict[str, tuple[int, str]] = {}
        for index, task in enumerate(group.get("Tasks") or []):
            role = _task_role(task.get("Lifecycle"), index)
            if role is not None:
                tasks[task["Name"]] = role
        lifecycle[group["Name"]] = tasks
    return lifecycle


def _task_role(lifecycle: dict[str, object] | None, index: int) -> tuple[int, str] | None:
    """Return a task's (sort order, label) from its lifecycle block, or None to skip.

    A task with no lifecycle block is a main task. Poststop tasks return None so
    they are excluded from the deploy view.
    """
    if not lifecycle:
        return (1_000 + index, "main")
    hook = lifecycle.get("Hook")
    if hook == "prestart":
        return (index, "prestart")
    if hook == "poststart":
        return (2_000 + index, "sidecar" if lifecycle.get("Sidecar") else "poststart")
    if hook == "poststop":
        return None
    return (1_000 + index, "main")


# Outcome labels carry the same color as their glyph so the status word reads as
# success/failure at a glance, not just the leading mark.
_OUTCOME_ROW: dict[DeployStatus, tuple[str, str]] = {
    DeployStatus.DEPLOYED: ok_row("deployed"),
    DeployStatus.FAILED: fail_row("failed"),
    DeployStatus.TIMEOUT: warn_row("still deploying"),
}


async def _running_job_names(client: NomadClient) -> set[str]:
    """Return the names of jobs currently running in the cluster."""
    jobs = await client.jobs.list()
    return {j.name for j in jobs if j.status == "running"}


# allow_interspersed_args lets options follow the positional JOB argument;
# Typer groups disable that by default, which would parse flags as subcommands.
app = typer.Typer(context_settings={"allow_interspersed_args": True})


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
        bool,
        typer.Option("--dry-run", "-n", help="Resolve and validate without registering."),
    ] = False,
    verbose: VerboseOption = 0,
) -> None:
    """Deploy one or more not-yet-running job files and watch them roll out.

    Only jobs that are not already running are offered; use plan to preview changes
    to a running job. Each selected file is validated, registered, and watched live:
    service jobs follow their deployment to success, while batch and system jobs
    follow their allocations. Use --detach to register and return without watching.
    """
    configure_verbosity(ctx, verbose)
    exit_code = asyncio.run(_run(job_arg=job, detach=detach, dry_run=dry_run))
    if exit_code != 0:
        raise typer.Exit(exit_code)


async def _run(*, job_arg: str | None, detach: bool, dry_run: bool) -> int:  # noqa: PLR0911
    """Resolve not-running candidates, validate, register, and watch the rollout.

    Returns the exit code: 0 on clean success, 1 on any failure. With ``detach`` the
    jobs are compiled and registered but the rollout is not watched.
    """
    files = discover_job_files(load_job_directories())
    config = NomadConfig.resolve()
    async with NomadClient.from_config(config) as client:
        running = await _running_job_names(client)
        candidates = candidates_for(files, exclude_names=running)
        if not candidates:
            pp.info("No deployable job files (all known jobs are already running).")
            return 0

        resolution = resolve_targets(candidates, job_arg, name_of=lambda c: c.name)
        targets = await select_candidates(
            resolution, "Select jobs to run", label_of=lambda c: f"{c.name}  [{c.file.path.name}]"
        )
        if targets is None:
            return 0
        if not targets:
            pp.error(f"No not-running job file matching '{job_arg}'")
            return 1

        try:
            nomad = NomadBinary.create(config)
            # dict.fromkeys dedups so a multi-job file is validated once.
            for path in dict.fromkeys(c.file.path for c in targets):
                nomad.validate(path)
        except NomadBinaryError as exc:
            pp.error(str(exc))
            return 1

        if dry_run:
            for c in targets:
                pp.dryrun(f"would run {c.name} ({c.file.path})")
            return 0

        if detach:
            return await _register_detached(client, targets, nomad)

        outcomes = await _deploy_all(client, targets, nomad)

    return 0 if all(o.status is DeployStatus.DEPLOYED for o in outcomes) else 1


async def _register_detached(
    client: NomadClient, targets: list[JobCandidate], nomad: NomadBinary
) -> int:
    """Compile and register every target concurrently, then return without watching.

    Mirrors ``nomad job run -detach``: each job file is compiled to JSON and
    registered, surfacing any register warnings, but the rollout is not polled. A
    per-job compile or register failure is reported and does not abort the others.
    Returns 0 only when every job registered successfully.
    """

    async def register_one(candidate: JobCandidate) -> tuple[str, str | None, str]:
        try:
            body = await asyncio.to_thread(nomad.compile_to_json, candidate.file.path)
            resp = await client.jobs.register(body)
        except (NomadBinaryError, NomadError) as exc:
            return (candidate.name, str(exc), "")
        return (candidate.name, None, resp.warnings)

    results = await asyncio.gather(*(register_one(c) for c in targets))
    registered = [name for name, err, _ in results if err is None]
    if registered:
        pp.success(f"Registered {len(registered)} job(s)", details=registered)
    for name, err, warnings in results:
        if err is not None:
            pp.error(f"{name} failed to register", details=[err])
        elif warnings:
            pp.warning(f"{name}: {warnings}")
    return 0 if all(err is None for _, err, _ in results) else 1


async def _deploy_all(
    client: NomadClient, targets: list[JobCandidate], nomad: NomadBinary
) -> list[DeployOutcome]:
    """Register and watch every target concurrently under one live panel.

    Args:
        client: Authenticated Nomad client.
        targets: The job candidates to register and watch.
        nomad: Configured `nomad` binary handle for the compile step.

    Returns:
        Ordered list of outcomes, one per target.
    """
    # Resolve node IDs to names once so every job's detail rows can show placement.
    node_names = await node_names_by_id(client)

    async def do_work(candidate: JobCandidate, update: PanelUpdate) -> DeployOutcome:
        return await _deploy_one(
            client, candidate, node_names=node_names, update=update, nomad=nomad
        )

    ordered = await run_rows(
        targets,
        do_work,
        label_of=lambda c: c.name,
        initial_phase="registering",
        finish_of=lambda o: _OUTCOME_ROW[o.status],
        running_title=f"Deploying {len(targets)} job(s)",
        final_title=_final_title,
    )

    report_outcomes(
        ordered,
        name_of=lambda o: o.name,
        detail_of=lambda o: o.detail,
        is_warn=lambda o: o.status is DeployStatus.TIMEOUT,
        is_fail=lambda o: o.status is DeployStatus.FAILED,
        fail_verb="deploy",
        warn_fallback="still deploying",
        warnings_of=lambda o: o.warnings,
    )
    return ordered


def _final_title(outcomes: list[DeployOutcome], elapsed_seconds: float) -> str:
    """Build the final panel title with deployed totals and elapsed seconds."""
    return final_panel_title(
        outcomes,
        elapsed_seconds,
        verb="Deployed",
        succeeded=lambda o: o.status is DeployStatus.DEPLOYED,
    )


async def _deploy_one(
    client: NomadClient,
    candidate: JobCandidate,
    *,
    node_names: dict[str, str],
    update: PanelUpdate,
    nomad: NomadBinary,
) -> DeployOutcome:
    """Compile, register, and watch one job to a terminal deploy state.

    Service jobs are watched via their deployment; batch/system jobs (which create
    no deployment) are watched via their allocations. Never raises: Nomad/binary
    failures become a FAILED outcome so a sibling job's progress is unaffected.

    Args:
        client: Authenticated Nomad client.
        candidate: The job file and name to deploy.
        node_names: Map of node ID to node name for the per-allocation detail rows.
        update: Callback to update the live panel phase text and detail rows.
        nomad: Configured `nomad` binary handle for the compile step.

    Returns:
        The terminal outcome for this candidate.
    """
    try:
        update("compiling")
        # compile_to_json shells out to the nomad binary (blocking); run it off the
        # event loop so sibling deploys keep making progress concurrently.
        body = await asyncio.to_thread(nomad.compile_to_json, candidate.file.path)
        lifecycle = task_lifecycle(body)
        update("registering")
        resp = await client.jobs.register(body)
        outcome = await watch_deploy(
            client,
            candidate.name,
            node_names=node_names,
            lifecycle=lifecycle,
            update=update,
            since_index=resp.job_modify_index,
        )
        # Attach any register warnings so the caller can surface them after the panel closes.
        return replace(outcome, warnings=resp.warnings)
    except (NomadBinaryError, NomadError) as exc:
        return DeployOutcome(candidate.name, DeployStatus.FAILED, str(exc))


async def watch_deploy(
    client: NomadClient,
    job_id: str,
    *,
    node_names: dict[str, str],
    lifecycle: TaskLifecycle,
    update: PanelUpdate,
    since_index: int = 0,
) -> DeployOutcome:
    """Poll a registered job until its deployment (or allocations) settle or time out.

    Service jobs expose a deployment that tracks health; batch/system jobs have no
    deployment so alloc statuses are used instead. Either way the job's allocations
    are fetched each tick to show where each one is placed and its status. The poll
    loop is bounded by a wall-clock deadline to avoid hanging on a stalled cluster.

    Args:
        client: Authenticated Nomad client.
        job_id: The Nomad job ID to poll.
        node_names: Map of node ID to node name for the per-allocation detail rows.
        lifecycle: Task ordering and labels from the compiled job spec.
        update: Callback to update the live panel phase text and detail rows.
        since_index: The ``JobModifyIndex`` from this registration. Deployments
            created before it belong to a previous run and are ignored so a re-run
            of a dead job is not reported as instantly deployed off a stale record.

    Returns:
        The terminal deploy outcome for this job.
    """
    deadline = time.monotonic() + DEPLOY_TIMEOUT_SECONDS
    while True:
        try:
            allocs = await client.jobs.allocations(job_id)
            deployments = await client.jobs.deployments(job_id)
            # The plural endpoint's ordering is undocumented, so pick this run's
            # deployment by index rather than trusting position. A job that has ever
            # run keeps its prior deployments listed; ignoring those created before
            # this registration is what stops a stale "successful" record from
            # ending the watch the instant a dead job is re-run.
            mine = [d for d in deployments if d.create_index >= since_index]
            latest = max(mine, key=lambda d: d.create_index) if mine else None
            dep = await client.deployments.read(latest.id) if latest else None
        except NomadDecodeError as exc:
            # A freshly-placed allocation can momentarily serialize in a shape we
            # cannot decode (e.g. TaskStates: null before its tasks start). Skip
            # this tick and retry rather than failing an otherwise-healthy deploy;
            # the deadline below is the backstop if it never recovers.
            pp.debug(f"{job_id}: skipping poll after transient decode error: {exc}")
        else:
            children = alloc_children(allocs, node_names, lifecycle)
            if dep is not None:  # service job: follow this run's deployment
                if dep.status == _DEPLOY_SUCCESS:
                    return DeployOutcome(job_id, DeployStatus.DEPLOYED)
                if dep.status in _DEPLOY_FAILURE:
                    return DeployOutcome(job_id, DeployStatus.FAILED, dep.status_description)
                update(deploy_phase(dep), children)
            elif deployments:  # service job whose new deployment has not appeared yet
                update("registering", children)
            else:  # batch/system job: follow allocations
                running = sum(1 for a in allocs if a.client_status in HEALTHY_ALLOC_STATUSES)
                if allocs and running == len(allocs):
                    return DeployOutcome(job_id, DeployStatus.DEPLOYED)
                update(f"placing {running}/{len(allocs) or '?'} allocs", children)
        if time.monotonic() >= deadline:
            return DeployOutcome(job_id, DeployStatus.TIMEOUT, "deploy still in progress")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
