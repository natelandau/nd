"""Resolve a job, allocation, and task through the Nomad API client.

Shared by every command that acts on a single task: each picks a job (by optional name
substring), then its allocation (auto when one, prompt when several), then a task
(auto when one, prompt when several, or a ``--task`` override). A command that acts on
a whole allocation stops before the task stage. Commands that need a live target resolve
running jobs/allocations/tasks only; ``nd logs`` passes ``running_only=False`` so a dead
or completed task's logs stay reachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp

from nd.nomad import NomadClient
from nd.targets.selection import pick_single, resolve_targets, select_one_candidate
from nd.ui.prompts import (
    INTERACTIVE_REMEDY,
    NAME_JOB_REMEDY,
    PromptUnavailableError,
    require_prompt,
)
from nd.ui.text import short_id

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nd.nomad.config import NomadConfig
    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.job import JobListStub


class SelectionError(Exception):
    """Raised when a target cannot be resolved and the command should exit non-zero."""


@dataclass(frozen=True)
class ResolvedAllocation:
    """A resolved allocation target, for commands that act on a whole allocation."""

    job_name: str
    alloc_id: str


@dataclass(frozen=True)
class ResolvedTarget(ResolvedAllocation):
    """A fully resolved single-task target: the chosen job, allocation, and task."""

    task: str


@dataclass(frozen=True)
class _TargetFilter:
    """The live-only-vs-any policy applied at every selection stage.

    ``nd exec`` resolves with ``running_only`` (only running jobs/allocs/tasks are
    selectable, since you cannot shell into a dead task); ``nd logs`` resolves with it
    off so a dead task's logs stay reachable. Holding the policy in one place keeps the
    job, allocation, and task stages from each re-deriving the same filter and label.
    """

    running_only: bool

    @property
    def qualifier(self) -> str:
        """The word woven into "No {qualifier}jobs/allocations/tasks" messages."""
        return "running " if self.running_only else ""

    def jobs(self, jobs: list[JobListStub]) -> list[JobListStub]:
        """Keep only running jobs when the policy is live-only."""
        return [j for j in jobs if j.is_running] if self.running_only else jobs

    def allocs(self, allocs: list[AllocListStub]) -> list[AllocListStub]:
        """Keep only running allocations when the policy is live-only."""
        return [a for a in allocs if a.client_status == "running"] if self.running_only else allocs

    def task_names(self, alloc: AllocListStub) -> list[str]:
        """Return the allocation's task names, limited to running tasks when live-only."""
        if self.running_only:
            return sorted(n for n, s in alloc.task_states.items() if s.state == "running")
        return sorted(alloc.task_states)


def _alloc_label(alloc: AllocListStub) -> str:
    """Render an allocation for a selection prompt (short id, group, client status)."""
    return f"{short_id(alloc.id)}  {alloc.task_group} ({alloc.client_status})"


def _task_label(alloc: AllocListStub, name: str) -> str:
    """Render a task name with its current state for a selection prompt."""
    return f"{name} ({alloc.task_states[name].state})"


async def _resolve_job(
    client: NomadClient, *, job_arg: str | None, target_filter: _TargetFilter
) -> JobListStub | None:
    """Resolve the job stage shared by every resolver, prompting only when ambiguous.

    Returns the chosen job, or None when nothing is selectable and no job was named, or
    the user cancels the prompt. Each of those cases reports itself.

    Raises:
        SelectionError: If the job argument matches nothing selectable.
    """
    qualifier = target_filter.qualifier
    jobs = await client.jobs.list()
    candidates = target_filter.jobs(jobs)
    pp.debug(f"GET /v1/jobs -> {len(candidates)} selectable of {len(jobs)} jobs")
    # A named job that is not selectable must fail loudly even when nothing is running,
    # so only the unnamed case exits soft; the named one falls through to the miss below.
    if not candidates and job_arg is None:
        pp.info(f"No {qualifier}jobs")
        return None

    resolution = resolve_targets(candidates, job_arg, name_of=lambda j: j.name)
    if job_arg is not None and not resolution.candidates:
        msg = f"No {qualifier}job matching '{job_arg}'"
        raise SelectionError(msg)
    require_prompt(needed=resolution.needs_prompt, what="Job selection", remedy=NAME_JOB_REMEDY)
    job = await select_one_candidate(resolution, "Select a job", label_of=lambda j: j.name)
    if job is None:
        pp.info("Nothing selected")
    return job


async def _selectable_allocs(
    client: NomadClient, *, job: JobListStub, target_filter: _TargetFilter
) -> list[AllocListStub]:
    """Fetch the job's allocations that pass the filter.

    Raises:
        SelectionError: If the job has no selectable allocation.
    """
    allocs = await client.jobs.allocations(job.id)
    candidates = target_filter.allocs(allocs)
    pp.debug(f"GET /v1/job/{job.id}/allocations -> {len(candidates)} selectable of {len(allocs)}")
    if not candidates:
        msg = f"No {target_filter.qualifier}allocations for '{job.name}'"
        raise SelectionError(msg)
    return candidates


async def _resolve_job_and_alloc(
    client: NomadClient,
    *,
    job_arg: str | None,
    target_filter: _TargetFilter,
    alloc_arg: str | None = None,
    alloc_remedy: str = INTERACTIVE_REMEDY,
) -> tuple[JobListStub, AllocListStub] | None:
    """Resolve the job and allocation stages shared by every single-target resolver.

    ``alloc_arg`` picks the one allocation whose ID starts with it, so a script can
    choose without a prompt. Returns the chosen job and allocation, or None when nothing
    is selectable and no job was named, or the user cancels a prompt. Each of those cases
    reports itself.

    Raises:
        SelectionError: If the job or allocation argument matches nothing selectable, the
            allocation argument matches several allocations, or the job has no selectable
            allocation.
    """
    job = await _resolve_job(client=client, job_arg=job_arg, target_filter=target_filter)
    if job is None:
        return None

    alloc_candidates = await _selectable_allocs(client=client, job=job, target_filter=target_filter)
    if alloc_arg is not None:
        # Prefix match, as Nomad's own CLI matches allocation IDs; like that CLI, an
        # ambiguous prefix is an error rather than a prompt the flag promised to skip
        alloc_candidates = [a for a in alloc_candidates if a.id.startswith(alloc_arg)]
        if len(alloc_candidates) != 1:
            matched = ", ".join(short_id(a.id) for a in alloc_candidates) or "none"
            msg = (
                f"Expected one {target_filter.qualifier}allocation of '{job.name}' "
                f"with an ID starting '{alloc_arg}', matched: {matched}"
            )
            raise SelectionError(msg)
    require_prompt(
        needed=len(alloc_candidates) > 1, what="Allocation selection", remedy=alloc_remedy
    )
    alloc = await pick_single(alloc_candidates, "Select an allocation", label_of=_alloc_label)
    if alloc is None:
        pp.info("Nothing selected")
        return None
    return job, alloc


async def _choose_task(
    task_names: list[str],
    *,
    task_arg: str | None,
    scope: str,
    qualifier: str,
    label_of: Callable[[str], str],
) -> str | None:
    """Pick the task stage's name: ``task_arg`` when given, else the lone name or a prompt.

    ``scope`` names where the tasks were looked for, such as ``allocation 1a2b3c4d``, for
    the error messages. Returns None when the user cancels the prompt, which reports itself.

    Raises:
        SelectionError: If there are no task names, or ``task_arg`` is not one of them.
        PromptUnavailableError: If several names need a prompt the session cannot show.
    """
    if not task_names:
        msg = f"No {qualifier}tasks in {scope}"
        raise SelectionError(msg)
    if task_arg is not None:
        if task_arg not in task_names:
            msg = f"No {qualifier}task '{task_arg}' in {scope}"
            raise SelectionError(msg)
        return task_arg
    require_prompt(needed=len(task_names) > 1, what="Task selection", remedy="pass --task")
    chosen = await pick_single(task_names, "Select a task", label_of=label_of)
    if chosen is None:
        pp.info("Nothing selected")
    return chosen


async def resolve_allocation(
    client: NomadClient, *, job_arg: str | None
) -> ResolvedAllocation | None:
    """Resolve a running job and one of its running allocations, prompting only where ambiguous.

    Use it for an action on a whole allocation, where a task prompt would ask a question
    the action does not need answered. Returns the resolved allocation, or None when
    nothing is selectable and no job was named, or the user cancels a prompt (the caller
    exits 0). Each of those cases reports itself.

    Raises:
        SelectionError: If an argument matches nothing selectable (the caller exits 1).
        PromptUnavailableError: If a choice needs a prompt the session cannot show (the
            caller exits 1).
    """
    resolved = await _resolve_job_and_alloc(
        client=client, job_arg=job_arg, target_filter=_TargetFilter(running_only=True)
    )
    if resolved is None:
        return None
    job, alloc = resolved
    return ResolvedAllocation(job_name=job.name, alloc_id=alloc.id)


async def resolve_alloc_task(
    client: NomadClient,
    *,
    job_arg: str | None,
    task_arg: str | None,
    alloc_arg: str | None = None,
    alloc_remedy: str = INTERACTIVE_REMEDY,
    running_only: bool = True,
) -> ResolvedTarget | None:
    """Resolve a job, allocation, and task, prompting only where ambiguous.

    With ``running_only`` (the default) only running jobs, allocations, and tasks are
    offered. ``nd logs`` passes ``running_only=False`` so a dead or completed task's logs
    are still reachable. ``alloc_arg`` keeps only allocations whose ID starts with it, and
    ``alloc_remedy`` is the fix named when the allocation prompt cannot be shown, for a
    command that offers a flag to skip it. Returns the resolved target, or None when
    nothing is selectable and no job was named, or the user cancels a prompt (the caller
    exits 0). Each of those cases reports itself.

    Raises:
        SelectionError: If an argument matches nothing selectable (the caller exits 1).
        PromptUnavailableError: If a choice needs a prompt the session cannot show (the
            caller exits 1).
    """
    target_filter = _TargetFilter(running_only=running_only)
    resolved = await _resolve_job_and_alloc(
        client=client,
        job_arg=job_arg,
        alloc_arg=alloc_arg,
        alloc_remedy=alloc_remedy,
        target_filter=target_filter,
    )
    if resolved is None:
        return None
    job, alloc = resolved

    task = await _choose_task(
        task_names=target_filter.task_names(alloc),
        task_arg=task_arg,
        scope=f"allocation {short_id(alloc.id)}",
        qualifier=target_filter.qualifier,
        label_of=lambda n: _task_label(alloc, n),
    )
    if task is None:
        return None
    return ResolvedTarget(job_name=job.name, alloc_id=alloc.id, task=task)


async def resolve_task_in_every_alloc(
    client: NomadClient, *, job_arg: str | None, task_arg: str | None
) -> list[ResolvedTarget] | None:
    """Resolve a running job and one task name, targeting that task in every running allocation.

    Use it to act on every copy of a task at once, such as from a scheduled script, where
    allocation IDs change on each deploy and a prompt cannot be answered. The task name
    is chosen once from the running tasks across all allocations, prompting only when
    several exist and ``task_arg`` is None. Allocations without that task are left out,
    and one whose copy of the task is not running is named in a warning, so a skipped
    copy is visible. Returns the targets in allocation order, or None when nothing is
    selectable and no job was named, or the user cancels a prompt (the caller exits 0).
    Each of those cases reports itself.

    Raises:
        SelectionError: If an argument matches nothing selectable (the caller exits 1).
        PromptUnavailableError: If a choice needs a prompt the session cannot show (the
            caller exits 1).
    """
    target_filter = _TargetFilter(running_only=True)
    job = await _resolve_job(client=client, job_arg=job_arg, target_filter=target_filter)
    if job is None:
        return None
    allocs = await _selectable_allocs(client=client, job=job, target_filter=target_filter)

    tasks_by_alloc = {alloc.id: target_filter.task_names(alloc) for alloc in allocs}
    task = await _choose_task(
        task_names=sorted({name for names in tasks_by_alloc.values() for name in names}),
        task_arg=task_arg,
        scope=f"any allocation of '{job.name}'",
        qualifier=target_filter.qualifier,
        label_of=str,
    )
    if task is None:
        return None
    not_running = [
        f"{short_id(alloc.id)} ({alloc.task_states[task].state})"
        for alloc in allocs
        if task in alloc.task_states and task not in tasks_by_alloc[alloc.id]
    ]
    if not_running:
        pp.warning(f"Skipping task {task} where it is not running", details=not_running)
    return [
        ResolvedTarget(job_name=job.name, alloc_id=alloc.id, task=task)
        for alloc in allocs
        if task in tasks_by_alloc[alloc.id]
    ]


async def _exit_code_for[T](resolution: Awaitable[T | None]) -> tuple[int, T | None]:
    """Await a resolver, reporting a selection failure or unavailable prompt as exit 1."""
    try:
        return 0, await resolution
    except (SelectionError, PromptUnavailableError) as exc:
        pp.error(str(exc))
        return 1, None


async def resolve_with_client(
    client: NomadClient,
    *,
    job_arg: str | None,
    task_arg: str | None,
    alloc_arg: str | None = None,
    alloc_remedy: str = INTERACTIVE_REMEDY,
    running_only: bool = True,
) -> tuple[int, ResolvedTarget | None]:
    """Resolve a target through an already-open client, mapping failures to an exit code.

    Resolve on a client the caller owns, so the connection stays open past resolution and
    the caller can act on the target over it. :func:`resolve_target` wraps this for
    callers that only need the target. The arguments match :func:`resolve_alloc_task`.
    Returns ``(exit_code, target)``: a target with code 0 on success, ``(0, None)`` when
    there is nothing to act on or the user cancels, and ``(1, None)`` when an argument
    matched nothing or a needed prompt could not be shown.
    """
    return await _exit_code_for(
        resolve_alloc_task(
            client=client,
            job_arg=job_arg,
            task_arg=task_arg,
            alloc_arg=alloc_arg,
            alloc_remedy=alloc_remedy,
            running_only=running_only,
        )
    )


async def resolve_every_alloc_with_client(
    client: NomadClient, *, job_arg: str | None, task_arg: str | None
) -> tuple[int, list[ResolvedTarget] | None]:
    """Resolve a task in every running allocation, mapping failures to an exit code.

    The every-allocation counterpart of :func:`resolve_with_client`, with the same
    ``(exit_code, targets)`` contract.
    """
    return await _exit_code_for(
        resolve_task_in_every_alloc(client=client, job_arg=job_arg, task_arg=task_arg)
    )


async def resolve_allocation_with_client(
    client: NomadClient, *, job_arg: str | None
) -> tuple[int, ResolvedAllocation | None]:
    """Resolve an allocation through an already-open client, mapping failures to an exit code.

    The allocation-only counterpart of :func:`resolve_with_client`, with the same
    ``(exit_code, target)`` contract.
    """
    return await _exit_code_for(resolve_allocation(client=client, job_arg=job_arg))


async def resolve_target(
    config: NomadConfig, *, job_arg: str | None, task_arg: str | None, running_only: bool = True
) -> tuple[int, ResolvedTarget | None]:
    """Open a client and resolve a target, mapping selection failures to an exit code.

    ``running_only`` is forwarded to :func:`resolve_alloc_task`: ``nd exec`` keeps the
    default (live targets only), ``nd logs`` passes False. Returns ``(exit_code,
    target)``: a target with code 0 on success, ``(0, None)`` when there is nothing to
    act on or the user cancels, and ``(1, None)`` when an argument matched nothing.
    """
    async with NomadClient(config) as client:
        return await resolve_with_client(
            client, job_arg=job_arg, task_arg=task_arg, running_only=running_only
        )
