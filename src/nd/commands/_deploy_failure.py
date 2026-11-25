"""Explain a failed deployment with its failed allocations' task events and stderr.

``nd run`` and ``nd update`` print this after the live panel closes, so the user sees
why a rollout failed without running ``nd logs`` by hand.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp
from rich.console import Group
from rich.text import Text

from nd.constants import (
    DEPLOY_FAILURE_EVENTS_PER_TASK,
    DEPLOY_FAILURE_MAX_ALLOCS,
    DEPLOY_FAILURE_STDERR_BYTES,
    DEPLOY_FAILURE_STDERR_LINES,
)
from nd.nodes import node_label
from nd.nomad.errors import NomadError
from nd.ui.panels import status_table, titled_panel
from nd.ui.styles import muted, status_cell
from nd.ui.text import short_id, strip_terminal_controls, untrusted_markup

if TYPE_CHECKING:
    from rich.console import RenderableType

    from nd.commands._lifecycle import DeployOutcome
    from nd.nomad import NomadClient
    from nd.nomad.models.allocation import AllocListStub, TaskEvent, TaskState
    from nd.ui.links import WebUi


@dataclass(frozen=True, kw_only=True)
class FailedTask:
    """One task of a failed allocation, with what it last did and printed.

    Attributes:
        name: The task name.
        events: The task's most recent events, oldest first.
        stderr_lines: The last lines the task wrote to stderr. Empty when the task
            never started or the log could not be read.
        stderr_error: Why stderr could not be read, or empty.
    """

    name: str
    events: tuple[TaskEvent, ...]
    stderr_lines: tuple[str, ...] = ()
    stderr_error: str = ""


@dataclass(frozen=True, kw_only=True)
class FailedAlloc:
    """An allocation the failed deployment placed that failed or was unhealthy.

    Attributes:
        alloc_id: The full allocation ID.
        name: The allocation name, such as ``web.app[0]``.
        node_id: The node the allocation was placed on.
        node: The node's display name.
        client_status: The allocation's client status.
        tasks: The tasks that explain the failure.
    """

    alloc_id: str
    name: str
    node_id: str
    node: str
    client_status: str
    tasks: tuple[FailedTask, ...]


def _troubled_tasks(alloc: AllocListStub) -> dict[str, TaskState]:
    """Pick the tasks that explain the failure: failed or restarted, else every task.

    A task that runs but fails its health check neither fails nor restarts, so falling
    back to every task still shows the event that marked the allocation unhealthy.
    """
    troubled = {
        name: state
        for name, state in alloc.task_states.items()
        if state.failed or state.restarts > 0
    }
    return troubled or alloc.task_states


def _tail_lines(text: str) -> tuple[str, ...]:
    """Keep the last stderr lines, dropping a first line the byte limit cut in half.

    A tail that is a single line keeps it, cut or not, so a task that logs one long
    line still shows something.
    """
    lines = text.splitlines()
    if len(text.encode()) >= DEPLOY_FAILURE_STDERR_BYTES and len(lines) > 1:
        lines = lines[1:]
    return tuple(lines[-DEPLOY_FAILURE_STDERR_LINES:])


async def _failed_task(
    *, client: NomadClient, alloc_id: str, name: str, state: TaskState
) -> FailedTask:
    """Collect one task's recent events and, when it ever started, the end of its stderr."""
    events = tuple(state.events[-DEPLOY_FAILURE_EVENTS_PER_TASK:])
    # A task that never started (image pull or driver failure) has no log file; its
    # events already say why.
    if not state.started_at_ns:
        return FailedTask(name=name, events=events)
    try:
        text = await client.allocations.log_tail(
            alloc_id, task=name, stream="stderr", max_bytes=DEPLOY_FAILURE_STDERR_BYTES
        )
    except NomadError as exc:
        return FailedTask(name=name, events=events, stderr_error=str(exc))
    return FailedTask(
        name=name,
        events=events,
        stderr_lines=_tail_lines(text),
    )


async def collect_failed_allocs(
    client: NomadClient,
    allocs: list[AllocListStub],
    *,
    job_version: int,
    node_names: dict[str, str],
) -> tuple[FailedAlloc, ...]:
    """Gather what explains a failed deployment, for printing once the live panel closes.

    Reads the task events already in ``allocs`` and fetches the end of each troubled
    task's stderr. A log that cannot be read is recorded on its task rather than
    raised, so the deploy still reports as failed.

    Args:
        client: Authenticated Nomad client.
        allocs: The job's allocations from the poll that saw the deployment fail.
        job_version: The failed deployment's job version, which picks out the
            allocations it placed.
        node_names: Map of node ID to node name.

    Returns:
        tuple[FailedAlloc, ...]: Up to ``DEPLOY_FAILURE_MAX_ALLOCS`` failed allocations,
        newest first.
    """
    failed = sorted(
        (a for a in allocs if a.job_version == job_version and a.is_deploy_failure),
        key=lambda a: a.create_index,
        reverse=True,
    )[:DEPLOY_FAILURE_MAX_ALLOCS]

    async def explain(alloc: AllocListStub) -> FailedAlloc:
        tasks = await asyncio.gather(
            *(
                _failed_task(client=client, alloc_id=alloc.id, name=name, state=state)
                for name, state in sorted(_troubled_tasks(alloc).items())
            )
        )
        return FailedAlloc(
            alloc_id=alloc.id,
            name=alloc.name,
            node_id=alloc.node_id,
            node=node_label(node_names=node_names, node_id=alloc.node_id),
            client_status=alloc.client_status,
            tasks=tuple(tasks),
        )

    return tuple(await asyncio.gather(*(explain(alloc) for alloc in failed)))


def _stderr_block(task: FailedTask) -> RenderableType | None:
    """Render a task's stderr tail under a muted heading, or None when there is nothing."""
    if task.stderr_error:
        return Text.from_markup(
            muted(
                f"{untrusted_markup(task.name)} stderr unavailable: {untrusted_markup(task.stderr_error)}"
            )
        )
    if not task.stderr_lines:
        return None
    heading = Text.from_markup(
        muted(f"{untrusted_markup(task.name)} stderr, last {len(task.stderr_lines)} lines")
    )
    # Log text is untrusted: plain Text never reads square brackets as markup.
    return Group(heading, Text(strip_terminal_controls("\n".join(task.stderr_lines))))


def _alloc_section(alloc: FailedAlloc, ui: WebUi) -> Group:
    """Render one failed allocation as a heading, its task events, and each task's stderr tail."""
    heading = Text.from_markup(
        f"{status_cell(alloc.client_status)} {untrusted_markup(alloc.name)} "
        f"{muted(short_id(alloc.alloc_id))} on "
        f"{ui.node(node_id=alloc.node_id, label=untrusted_markup(alloc.node))}"
    )
    table = status_table("TASK", "EVENT", "MESSAGE", overflow="fold")
    for task in alloc.tasks:
        for index, event in enumerate(task.events):
            # Name the task once, on its first event, so its events read as a group.
            table.add_row(
                untrusted_markup(task.name) if index == 0 else "",
                untrusted_markup(event.type),
                untrusted_markup(event.display_message),
            )
    blocks = [b for b in (_stderr_block(task) for task in alloc.tasks) if b is not None]
    return Group(heading, table, *blocks)


def render_deploy_failure(outcome: DeployOutcome, *, ui: WebUi) -> None:
    """Print one panel holding every failed allocation of a failed deployment.

    Pass it as ``explain_failure`` to ``run_outcome_rows`` so it follows the job's
    ``failed to deploy`` line. Prints nothing when no allocation explains the failure.

    Args:
        outcome: The failed job's outcome.
        ui: Link builder for the Nomad web UI.
    """
    if not outcome.failed_allocs:
        return
    sections: list[RenderableType] = []
    for index, alloc in enumerate(outcome.failed_allocs):
        if index:
            sections.append(Text())
        sections.append(_alloc_section(alloc, ui))
    title = (
        f"Failed allocations of {ui.job(job_id=outcome.name, label=untrusted_markup(outcome.name))}"
    )
    pp.console().print(titled_panel(Group(*sections), title=title, border_style="red", expand=True))
