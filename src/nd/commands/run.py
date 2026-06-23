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

from nd import jobspec
from nd.constants import DEPLOY_TIMEOUT_SECONDS, HEALTHY_ALLOC_STATUSES, POLL_INTERVAL_SECONDS
from nd.jobfiles import candidates_for, discover_job_files, load_job_directories
from nd.jobspec import JobSpecError
from nd.nomad import NomadClient, NomadConfig
from nd.nomad.errors import NomadError
from nd.selection import resolve_targets, select_candidates
from nd.ui.alloc_rows import alloc_children
from nd.ui.duration import summary_title
from nd.ui.live_panel import LiveRow, PanelUpdate, finish_row, run_live_panel
from nd.ui.styles import OUTCOME_GLYPH

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


_OUTCOME_ROW: dict[DeployStatus, tuple[str, str]] = {
    DeployStatus.DEPLOYED: (OUTCOME_GLYPH["ok"], "deployed"),
    DeployStatus.FAILED: (OUTCOME_GLYPH["fail"], "failed"),
    DeployStatus.TIMEOUT: (OUTCOME_GLYPH["warn"], "still deploying"),
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
        typer.Argument(help="Job to run; matches any not-running job whose name starts with this."),
    ] = None,
    dry_run: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--dry-run", "-n", help="Resolve and validate without registering."),
    ] = False,
    verbose: Annotated[
        int,
        typer.Option(
            "-v", "--verbose", count=True, help="Increase verbosity (-v debug, -vv trace)."
        ),
    ] = 0,
) -> None:
    """Deploy one or more not-yet-running job files and watch them roll out."""
    # Accept -v/-vv either before the command (root callback) or here; take the louder.
    verbose = max(getattr(ctx.obj, "verbose", 0), verbose)
    pp.configure(verbosity=verbose)
    exit_code = asyncio.run(_run(job_arg=job, dry_run=dry_run))
    if exit_code != 0:
        raise typer.Exit(exit_code)


async def _run(*, job_arg: str | None, dry_run: bool) -> int:
    """Resolve not-running candidates, validate, register, and watch the rollout.

    Returns the exit code: 0 on clean success, 1 on any failure.
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
            jobspec.ensure_nomad()
            # dict.fromkeys dedups so a multi-job file is validated once.
            for path in dict.fromkeys(c.file.path for c in targets):
                jobspec.validate(path, config)
        except JobSpecError as exc:
            pp.error(str(exc))
            return 1

        if dry_run:
            for c in targets:
                pp.dryrun(f"would run {c.name} ({c.file.path})")
            return 0

        outcomes = await _deploy_all(client, targets, config)

    return 0 if all(o.status is DeployStatus.DEPLOYED for o in outcomes) else 1


async def _deploy_all(
    client: NomadClient, targets: list[JobCandidate], config: NomadConfig
) -> list[DeployOutcome]:
    """Register and watch every target concurrently under one live panel.

    Args:
        client: Authenticated Nomad client.
        targets: The job candidates to register and watch.
        config: Resolved Nomad config, passed to the binary compile step.

    Returns:
        Ordered list of outcomes, one per target.
    """
    start = time.monotonic()
    # Resolve node IDs to names once so every job's detail rows can show placement.
    node_names = {node.id: node.name for node in await client.nodes.list()}
    pairs = [(c, LiveRow(label=c.name, phase="registering", started_at=start)) for c in targets]
    # Key by row identity so duplicate job names don't collapse into one entry.
    by_row: dict[int, JobCandidate] = {id(row): c for c, row in pairs}
    outcomes: dict[int, DeployOutcome] = {}

    async def worker(row: LiveRow, update: PanelUpdate) -> None:
        candidate = by_row[id(row)]
        outcome = await _deploy_one(
            client, candidate, node_names=node_names, update=update, config=config
        )
        glyph, label = _OUTCOME_ROW[outcome.status]
        finish_row(row, glyph, label)
        outcomes[id(row)] = outcome

    await run_live_panel(
        [row for _, row in pairs],
        worker,
        running_title=f"Deploying {len(targets)} job(s)",
        final_title=lambda secs: _final_title(list(outcomes.values()), secs),
    )

    ordered = [outcomes[id(row)] for _, row in pairs]
    for o in ordered:
        if o.status is DeployStatus.TIMEOUT:
            pp.warning(f"{o.name}: {o.detail or 'still deploying'}")
        elif o.status is DeployStatus.FAILED:
            pp.error(f"{o.name} failed to deploy", details=[o.detail] if o.detail else None)
        if o.warnings:
            pp.warning(f"{o.name}: {o.warnings}")
    return ordered


def _final_title(outcomes: list[DeployOutcome], elapsed_seconds: float) -> str:
    """Build the final panel title with deployed totals and elapsed seconds."""
    ok = sum(1 for o in outcomes if o.status is DeployStatus.DEPLOYED)
    return summary_title("Deployed", ok, len(outcomes), elapsed_seconds)


async def _deploy_one(
    client: NomadClient,
    candidate: JobCandidate,
    *,
    node_names: dict[str, str],
    update: PanelUpdate,
    config: NomadConfig,
) -> DeployOutcome:
    """Compile, register, and watch one job to a terminal deploy state.

    Service jobs are watched via their deployment; batch/system jobs (which create
    no deployment) are watched via their allocations. Never raises: Nomad/jobspec
    failures become a FAILED outcome so a sibling job's progress is unaffected.

    Args:
        client: Authenticated Nomad client.
        candidate: The job file and name to deploy.
        node_names: Map of node ID to node name for the per-allocation detail rows.
        update: Callback to update the live panel phase text and detail rows.
        config: Resolved Nomad config, passed to the binary compile step.

    Returns:
        The terminal outcome for this candidate.
    """
    try:
        update("compiling")
        # compile_to_json shells out to the nomad binary (blocking); run it off the
        # event loop so sibling deploys keep making progress concurrently.
        body = await asyncio.to_thread(jobspec.compile_to_json, candidate.file.path, config)
        lifecycle = task_lifecycle(body)
        update("registering")
        resp = await client.jobs.register(body)
        outcome = await _watch(
            client, candidate.name, node_names=node_names, lifecycle=lifecycle, update=update
        )
        # Attach any register warnings so the caller can surface them after the panel closes.
        return replace(outcome, warnings=resp.warnings)
    except (JobSpecError, NomadError) as exc:
        return DeployOutcome(candidate.name, DeployStatus.FAILED, str(exc))


async def _watch(
    client: NomadClient,
    job_id: str,
    *,
    node_names: dict[str, str],
    lifecycle: TaskLifecycle,
    update: PanelUpdate,
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

    Returns:
        The terminal deploy outcome for this job.
    """
    deadline = time.monotonic() + DEPLOY_TIMEOUT_SECONDS
    while True:
        allocs = await client.jobs.allocations(job_id)
        children = alloc_children(allocs, node_names, lifecycle)
        deployments = await client.jobs.deployments(job_id)
        if deployments:  # service job: follow the most-recent deployment
            dep = await client.deployments.read(deployments[0].id)
            if dep.status == _DEPLOY_SUCCESS:
                return DeployOutcome(job_id, DeployStatus.DEPLOYED)
            if dep.status in _DEPLOY_FAILURE:
                return DeployOutcome(job_id, DeployStatus.FAILED, dep.status_description)
            update(deploy_phase(dep), children)
        else:  # batch/system job: follow allocations
            running = sum(1 for a in allocs if a.client_status in HEALTHY_ALLOC_STATUSES)
            if allocs and running == len(allocs):
                return DeployOutcome(job_id, DeployStatus.DEPLOYED)
            update(f"placing {running}/{len(allocs) or '?'} allocs", children)
        if time.monotonic() >= deadline:
            return DeployOutcome(job_id, DeployStatus.TIMEOUT, "deploy still in progress")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
