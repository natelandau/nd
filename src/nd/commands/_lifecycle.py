"""Watch a job deploy or drain to a terminal state, for the run, stop, and update commands."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp

from nd.commands._deploy_failure import FailedAlloc, collect_failed_allocs
from nd.commands._orchestration import Outcome, Severity
from nd.constants import (
    DEPLOY_TIMEOUT_SECONDS,
    HEALTHY_ALLOC_STATUSES,
    POLL_INTERVAL_SECONDS,
    STOP_TIMEOUT_SECONDS,
)
from nd.nomad.errors import NomadDecodeError, NomadError
from nd.nomad.models import decode_json
from nd.nomad.models.job import JobRegisterPayload
from nd.ui.alloc_rows import alloc_children

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nd.nomad import NomadClient
    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.deployment import Deployment
    from nd.nomad.models.job import JobListStub, TaskLifecycleSpec
    from nd.ui.alloc_rows import TaskLifecycle
    from nd.ui.live_panel import PanelUpdate

# Deployment statuses that mean the rollout is finished, one way or the other.
_DEPLOY_SUCCESS = "successful"
_DEPLOY_FAILURE = frozenset({"failed", "cancelled"})


@dataclass(frozen=True, kw_only=True)
class DeployOutcome(Outcome):
    """The result of deploying one job, with the allocations that explain a failure.

    Attributes:
        failed_allocs: The failed deployment's failed or unhealthy allocations, newest
            first. Empty unless the deployment failed.
    """

    failed_allocs: tuple[FailedAlloc, ...] = ()


@dataclass(frozen=True, kw_only=True)
class StopOutcome(Outcome):
    """The result of stopping one job, with what ``nd update`` needs to continue.

    Attributes:
        workload_stopped: The allocations reached a terminal state, even when the
            follow-up purge failed, so a re-register cannot overlap the old version.
        drained: Allocations seen in the terminal drain frame, matching the rows the
            user just watched drain.
    """

    workload_stopped: bool = False
    drained: int = 0


async def poll_until[T](
    check: Callable[[], Awaitable[T | None]],
    *,
    timeout_seconds: float,
    timed_out: T,
    subject: str,
) -> T:
    """Repeat ``check`` every poll interval until it returns a result or time runs out.

    The bound is on elapsed wall-clock time, not on poll count, so slow requests cannot
    stretch the wait past ``timeout_seconds``.

    Args:
        check: Fetch the current state and return the terminal result, or None to
            keep polling.
        timeout_seconds: How long to keep polling.
        timed_out: The result to return when time runs out.
        subject: What is being polled, for the debug line about a skipped poll.

    Returns:
        T: The first terminal result from ``check``, or ``timed_out``.
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            result = await check()
        except NomadDecodeError as exc:
            # A freshly placed or restarted allocation can briefly serialize in a shape
            # that does not decode (e.g. TaskStates: null before its tasks start). Skip
            # this tick rather than failing healthy work; the deadline is the backstop.
            pp.debug(f"{subject}: skipping poll after transient decode error: {exc}")
        else:
            if result is not None:
                return result
        if time.monotonic() >= deadline:
            return timed_out
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def deploy_phase(dep: Deployment) -> str:
    """Summarize a deployment's progress as ``<status>: <healthy>/<desired> healthy``.

    Aggregates counts across all task groups so the live panel shows a single
    meaningful number rather than per-group noise.
    """
    healthy = sum(tg.healthy_allocs for tg in dep.task_groups.values())
    desired = sum(tg.desired_total for tg in dep.task_groups.values())
    return f"{dep.status}: {healthy}/{desired} healthy"


def deploy_outcome(
    name: str,
    severity: Severity,
    *,
    done_label: str,
    detail: str = "",
    warnings: str = "",
    failed_allocs: tuple[FailedAlloc, ...] = (),
) -> DeployOutcome:
    """Build a deploy-shaped outcome, labeling its row by severity.

    ``nd run`` and ``nd update`` share the timeout and failure labels and differ only
    in the word for a clean finish.

    Args:
        name: The job name.
        severity: How the deploy finished.
        done_label: The row label for a clean finish, e.g. ``deployed``.
        detail: Why the deploy did not finish cleanly.
        warnings: Warnings Nomad returned on register.
        failed_allocs: The allocations that explain a failed deployment.

    Returns:
        DeployOutcome: The labeled outcome.
    """
    labels = {Severity.OK: done_label, Severity.WARN: "still deploying", Severity.FAIL: "failed"}
    return DeployOutcome(
        name=name,
        severity=severity,
        label=labels[severity],
        detail=detail,
        warnings=warnings,
        failed_allocs=failed_allocs,
    )


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
    payload = decode_json(data=body, type_=JobRegisterPayload)
    groups = payload.job.task_groups if payload.job else []
    lifecycle: TaskLifecycle = {}
    for group in groups:
        tasks: dict[str, tuple[int, str]] = {}
        for index, task in enumerate(group.tasks):
            role = _task_role(lifecycle=task.lifecycle, index=index)
            if role is not None:
                tasks[task.name] = role
        lifecycle[group.name] = tasks
    return lifecycle


def is_service_job(body: bytes) -> bool:
    """Report whether a compiled job spec is a service job, to pick how its deploy is watched.

    Args:
        body: The compiled ``{"Job": {...}}`` JSON from ``nomad job run -output``.

    Returns:
        bool: True for a service job, including one whose file leaves ``type`` unset.
    """
    payload = decode_json(data=body, type_=JobRegisterPayload)
    return payload.job is None or payload.job.is_service


def _task_role(lifecycle: TaskLifecycleSpec | None, index: int) -> tuple[int, str] | None:
    """Return a task's (sort order, label) from its lifecycle block, or None to skip.

    A task with no lifecycle block is a main task. Poststop tasks return None so
    they are excluded from the deploy view.
    """
    hook = lifecycle.hook if lifecycle else None
    if hook == "prestart":
        return (index, "prestart")
    if hook == "poststart":
        return (2_000 + index, "sidecar" if lifecycle and lifecycle.sidecar else "poststart")
    if hook == "poststop":
        return None
    return (1_000 + index, "main")


async def watch_deploy(  # noqa: PLR0913
    client: NomadClient,
    job_id: str,
    *,
    node_names: dict[str, str],
    lifecycle: TaskLifecycle,
    update: PanelUpdate,
    done_label: str,
    is_service: bool,
    since_index: int = 0,
) -> DeployOutcome:
    """Poll a registered job until its deployment (or allocations) settle or time out.

    Service jobs expose a deployment that tracks health; batch/system jobs have no
    deployment so alloc statuses are used instead. Either way the job's allocations
    are fetched each tick to show where each one is placed and its status. A failed
    deployment's outcome carries its failed allocations' task events and stderr.

    Args:
        client: Authenticated Nomad client.
        job_id: The Nomad job ID to poll.
        node_names: Map of node ID to node name for the per-allocation detail rows.
        lifecycle: Task ordering and labels from the compiled job spec.
        update: Callback to update the live panel phase text and detail rows.
        done_label: The row label for a clean finish, e.g. ``deployed``.
        is_service: Whether the job is a service job, which waits for a deployment.
        since_index: The ``JobModifyIndex`` from this registration. Deployments and
            allocations from before it belong to a previous run and are ignored so a
            re-run of a dead job is not reported as instantly deployed off a stale
            record.

    Returns:
        DeployOutcome: The terminal deploy outcome for this job.
    """

    def finished(
        severity: Severity, detail: str = "", failed_allocs: tuple[FailedAlloc, ...] = ()
    ) -> DeployOutcome:
        return deploy_outcome(
            job_id, severity, done_label=done_label, detail=detail, failed_allocs=failed_allocs
        )

    async def check() -> DeployOutcome | None:
        allocs, deployments = await asyncio.gather(
            client.jobs.allocations(job_id), client.jobs.deployments(job_id)
        )
        # The plural endpoint's ordering is undocumented, so pick this run's deployment
        # by index rather than trusting position. A job that has ever run keeps its prior
        # deployments listed; ignoring those created before this registration is what
        # stops a stale "successful" record from ending the watch the instant a dead job
        # is re-run. The earliest remaining one is this registration's: a later one is an
        # auto-revert rollback or another registration, whose success says nothing about
        # the spec deployed here.
        mine = [d for d in deployments if d.create_index >= since_index]
        dep = min(mine, key=lambda d: d.create_index) if mine else None
        placed = [a for a in allocs if _placed_by_this_run(a, since_index=since_index)]
        # A previous run's finished allocations are history, not part of this deploy.
        shown = [a for a in allocs if a.create_index >= since_index or not a.is_terminal]
        children = alloc_children(shown, node_names, lifecycle)
        if dep is not None:  # service job: follow this run's deployment
            if dep.status == _DEPLOY_SUCCESS:
                return finished(Severity.OK)
            if dep.status in _DEPLOY_FAILURE:
                failed_allocs = await collect_failed_allocs(
                    client, allocs, job_version=dep.job_version, node_names=node_names
                )
                return finished(Severity.FAIL, dep.status_description, failed_allocs)
            update(deploy_phase(dep), children)
        elif is_service and not placed:
            # Service job whose deployment and allocations have not appeared yet. One
            # with allocations but no deployment of its own (updates disabled) falls
            # through to alloc counting so it can still finish.
            update("registering", children)
        else:  # batch/system job, or a service job with no deployment: follow allocations
            running = sum(1 for a in placed if a.client_status in HEALTHY_ALLOC_STATUSES)
            if placed and running == len(placed):
                return finished(Severity.OK)
            update(f"placing {running}/{len(placed) or '?'} allocs", children)
        return None

    return await poll_until(
        check,
        timeout_seconds=DEPLOY_TIMEOUT_SECONDS,
        timed_out=finished(Severity.WARN, "deploy still in progress"),
        subject=job_id,
    )


def _placed_by_this_run(alloc: AllocListStub, *, since_index: int) -> bool:
    """Report whether an allocation belongs to the registration at ``since_index``.

    A stopped job keeps its old allocations listed as "complete", which would read as
    this run's healthy placements and end the watch before anything is placed. An
    in-place update keeps the allocation's original create index, so a live
    allocation the scheduler touched after the registration also counts. A
    reschedule chain's replaced attempts are left out so a recovered failure does not
    hold the count below its total.
    """
    if alloc.is_replaced:
        return False
    if alloc.create_index >= since_index:
        return True
    return alloc.modify_index >= since_index and not alloc.is_retired


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


def phase_text(allocs: list[AllocListStub], *, pending: int) -> str:
    """Build the live phase label for a draining job.

    Args:
        allocs: The job's allocations from the latest poll.
        pending: How many of them are not yet terminal.

    Returns:
        str: The phase text for the job's row.
    """
    if not allocs:
        return "stopping"
    names = running_task_names(allocs)
    if names:
        # These are the tasks still alive mid-drain (shutdown-delay or post-stop
        # cleanup tasks); "waiting on" reads with the stop rather than implying the
        # task is happily running.
        return "waiting on: " + ", ".join(names)
    return f"draining {pending} allocs" if pending else "stopping"


async def stop_and_wait(
    client: NomadClient,
    job: JobListStub,
    update: PanelUpdate,
    *,
    purge: bool,
    node_names: dict[str, str],
    no_shutdown_delay: bool = False,
) -> StopOutcome:
    """Stop one job and poll its allocations until they are terminal or time out.

    Reports drain progress through ``update``: a phase summary plus a detail row
    per allocation and task (so post-stop tasks draining on each node are visible).
    When ``purge`` is set the job is garbage-collected only after the drain reaches a
    terminal state, so the post-stop tasks are watched first; a timed-out or failed
    drain leaves the job queryable for inspection rather than purging it.
    Never raises: a Nomad failure becomes a failed outcome so a sibling job's
    progress is unaffected.
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

        async def check() -> StopOutcome | None:
            start = time.perf_counter()
            allocs = await client.jobs.allocations(job.id)
            pending = sum(1 for a in allocs if not a.is_terminal)
            elapsed_ms = (time.perf_counter() - start) * 1000
            pp.trace(
                f"GET /v1/job/{job.id}/allocations -> {len(allocs)} allocs "
                f"({pending} not terminal), {elapsed_ms:.0f}ms"
            )
            if not pending:
                if purge:
                    return await _purge_dead_job(client, job, update=update, drained=len(allocs))
                return _stopped(job, drained=len(allocs))
            update(
                phase_text(allocs, pending=pending),
                alloc_children(allocs, node_names, None, stopping=True),
            )
            return None

        return await poll_until(
            check,
            timeout_seconds=STOP_TIMEOUT_SECONDS,
            timed_out=StopOutcome(
                name=job.name,
                severity=Severity.WARN,
                label="still draining",
                detail="stop requested, still draining",
            ),
            subject=job.id,
        )
    except NomadError as exc:
        return StopOutcome(name=job.name, severity=Severity.FAIL, label="failed", detail=str(exc))


def _stopped(job: JobListStub, *, drained: int) -> StopOutcome:
    """Build the outcome for a job whose allocations all reached a terminal state."""
    return StopOutcome(
        name=job.name,
        severity=Severity.OK,
        label="stopped",
        workload_stopped=True,
        drained=drained,
    )


async def _purge_dead_job(
    client: NomadClient, job: JobListStub, *, update: PanelUpdate, drained: int
) -> StopOutcome:
    """Garbage-collect a job that has already drained to a terminal state.

    Nomad has no per-job GC endpoint other than the purging deregister, so a clean
    stop is purged by re-issuing the deregister with ``purge=true`` once the drain has
    been watched to completion. ``no_shutdown_delay`` is not forwarded: the job is
    already dead here, so there are no live allocations for the flag to act on. A purge
    failure is a warning, not a failed stop, because the workload did come down.
    """
    try:
        update("purging")
        await client.jobs.stop(job.id, purge=True)
        pp.debug(f"DELETE /v1/job/{job.id}?purge=true -> garbage-collected dead job")
    except NomadError as exc:
        return StopOutcome(
            name=job.name,
            severity=Severity.WARN,
            label="stopped, purge failed",
            detail=f"stopped but purge failed: {exc}",
            workload_stopped=True,
            drained=drained,
        )
    return _stopped(job, drained=drained)
