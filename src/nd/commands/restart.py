"""The ``nd restart`` command: restart a task or allocation in place."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from nclutils import pp

from nd.commands._common import (
    VerboseOption,
    command_app,
    configure_verbosity,
    dry_run_option,
    record_step,
)
from nd.nomad import NomadClient, NomadConfig
from nd.targets import resolve_allocation_with_client, resolve_with_client
from nd.ui.text import short_id

app = command_app()


@app.callback(invoke_without_command=True)
def restart(
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(
            help="Running job to restart; matches any job whose name contains this. "
            "Omit to pick from a list."
        ),
    ] = None,
    task: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Restart only this task instead of the allocation."),
    ] = None,
    all_tasks: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--all-tasks",
            "-a",
            help="Also re-run tasks that already finished, such as prestart tasks.",
        ),
    ] = False,
    dry_run: Annotated[  # noqa: FBT002
        bool, dry_run_option("Show what would be restarted.")
    ] = False,
    verbose: VerboseOption = 0,
) -> None:
    """Restart a running allocation's tasks, or one task, in place.

    Resolves a running job and allocation, prompting only where the choice is ambiguous,
    then restarts its running tasks on the same node. --task restarts one task instead,
    and --all-tasks also re-runs tasks that already finished. Use it to bounce a hung
    process or make a task re-read its config, without the reschedule that stop and run
    cause.

    A success line means Nomad accepted the restart. Check `nd status` or `nd logs` to see
    the task come back.
    """
    verbose = configure_verbosity(ctx, verbose)
    if task is not None and all_tasks:
        msg = (
            f"--all-tasks restarts every task, so it cannot be combined with --task {task}; "
            "pass only one of them"
        )
        raise typer.BadParameter(message=msg, param_hint="--all-tasks")
    config = NomadConfig.resolve()
    exit_code = asyncio.run(
        _run(
            config=config,
            job=job,
            task=task,
            all_tasks=all_tasks,
            dry_run=dry_run,
            verbose=verbose,
        )
    )
    if exit_code != 0:
        raise typer.Exit(exit_code)


async def _run(
    *,
    config: NomadConfig,
    job: str | None,
    task: str | None,
    all_tasks: bool,
    dry_run: bool,
    verbose: int,
) -> int:
    """Resolve a live target and restart it, sharing one client between both steps.

    A named task resolves through the task picker so a typo fails before the restart is
    sent; without one, only the job and allocation are resolved, since the restart covers
    them all.

    Returns:
        int: The exit code: the resolver's code when there is nothing to restart, else 0.
    """
    async with NomadClient(config) as client:
        exit_code, target = await (
            resolve_with_client(client=client, job_arg=job, task_arg=task, running_only=True)
            if task is not None
            else resolve_allocation_with_client(client=client, job_arg=job)
        )
        if target is None:
            return exit_code
        job_name, alloc_id = target.job_name, target.alloc_id
        what = f"task {task}" if task is not None else "all tasks" if all_tasks else "running tasks"

        where = f"{what} in alloc {short_id(alloc_id)} ({job_name})"
        if dry_run:
            pp.dryrun(f"Would restart {where}")
            return 0

        with pp.step(f"Restarting {where}") as step:
            await record_step(
                coro=client.allocations.restart(alloc_id=alloc_id, task=task, all_tasks=all_tasks),
                step=step,
                verbose=verbose,
                method="POST",
                path=f"/client/allocation/{alloc_id}/restart",
            )

    pp.success(
        message=f"Restart requested for {where}",
        details=[f"run `nd status` or `nd logs {job_name}` to watch it come back"],
    )
    return 0
