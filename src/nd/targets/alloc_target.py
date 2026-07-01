"""Resolve a job, allocation, and task through the Nomad API client.

Shared by ``nd exec`` and ``nd logs``: both pick a single job (by optional name
substring), then its allocation (auto when one, prompt when several), then a task
(auto when one, prompt when several, or a ``--task`` override). ``nd exec`` needs a
live target, so it resolves running jobs/allocations/tasks only; ``nd logs`` passes
``running_only=False`` so a dead or completed task's logs stay reachable. The
resolved target is handed to a ``NomadBinary`` (the binary layer) to act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp

from nd.nomad import NomadClient
from nd.targets.selection import pick_single, resolve_targets, select_one_candidate

if TYPE_CHECKING:
    from nd.nomad.config import NomadConfig
    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.job import JobListStub


class SelectionError(Exception):
    """Raised when a target cannot be resolved and the command should exit non-zero."""


@dataclass(frozen=True)
class ResolvedTarget:
    """A fully resolved exec/logs target: the chosen job, allocation, and task."""

    job_name: str
    alloc_id: str
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
        return [j for j in jobs if j.status == "running"] if self.running_only else jobs

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
    return f"{alloc.id[:8]}  {alloc.task_group} ({alloc.client_status})"


def _task_label(alloc: AllocListStub, name: str) -> str:
    """Render a task name with its current state for a selection prompt."""
    return f"{name} ({alloc.task_states[name].state})"


async def resolve_alloc_task(
    client: NomadClient, *, job_arg: str | None, task_arg: str | None, running_only: bool = True
) -> ResolvedTarget | None:
    """Resolve a job, allocation, and task, prompting only where ambiguous.

    With ``running_only`` (the default, used by ``nd exec``) only running jobs,
    allocations, and tasks are offered. ``nd logs`` passes ``running_only=False`` so a
    dead or completed task's logs are still reachable. Returns the resolved target, or
    None when there is nothing to act on or the user cancels a prompt (the caller exits
    0). Each of those cases reports itself.

    Raises:
        SelectionError: If an argument matches nothing selectable (the caller exits 1).
    """
    target_filter = _TargetFilter(running_only=running_only)
    qualifier = target_filter.qualifier
    jobs = await client.jobs.list()
    candidates = target_filter.jobs(jobs)
    pp.debug(f"GET /v1/jobs -> {len(candidates)} selectable of {len(jobs)} jobs")
    if not candidates:
        pp.info(f"No {qualifier}jobs")
        return None

    resolution = resolve_targets(candidates, job_arg, name_of=lambda j: j.name)
    if job_arg is not None and not resolution.candidates:
        msg = f"No {qualifier}job matching '{job_arg}'"
        raise SelectionError(msg)
    job = await select_one_candidate(resolution, "Select a job", label_of=lambda j: j.name)
    if job is None:
        pp.info("Nothing selected")
        return None

    allocs = await client.jobs.allocations(job.id)
    alloc_candidates = target_filter.allocs(allocs)
    pp.debug(
        f"GET /v1/job/{job.id}/allocations -> {len(alloc_candidates)} selectable of {len(allocs)}"
    )
    if not alloc_candidates:
        msg = f"No {qualifier}allocations for '{job.name}'"
        raise SelectionError(msg)
    alloc = await pick_single(alloc_candidates, "Select an allocation", label_of=_alloc_label)
    if alloc is None:
        pp.info("Nothing selected")
        return None

    task_names = target_filter.task_names(alloc)
    if not task_names:
        msg = f"No {qualifier}tasks in allocation {alloc.id[:8]}"
        raise SelectionError(msg)
    if task_arg is not None:
        if task_arg not in task_names:
            msg = f"No {qualifier}task '{task_arg}' in allocation {alloc.id[:8]}"
            raise SelectionError(msg)
        task = task_arg
    else:
        chosen = await pick_single(
            task_names, "Select a task", label_of=lambda n: _task_label(alloc, n)
        )
        if chosen is None:
            pp.info("Nothing selected")
            return None
        task = chosen

    return ResolvedTarget(job_name=job.name, alloc_id=alloc.id, task=task)


async def resolve_target(
    config: NomadConfig, *, job_arg: str | None, task_arg: str | None, running_only: bool = True
) -> tuple[int, ResolvedTarget | None]:
    """Open a client and resolve a target, mapping selection failures to an exit code.

    ``running_only`` is forwarded to :func:`resolve_alloc_task`: ``nd exec`` keeps the
    default (live targets only), ``nd logs`` passes False. Returns ``(exit_code,
    target)``: a target with code 0 on success, ``(0, None)`` when there is nothing to
    act on or the user cancels, and ``(1, None)`` when an argument matched nothing.
    """
    async with NomadClient.from_config(config) as client:
        try:
            target = await resolve_alloc_task(
                client, job_arg=job_arg, task_arg=task_arg, running_only=running_only
            )
        except SelectionError as exc:
            pp.error(str(exc))
            return 1, None
    return 0, target
