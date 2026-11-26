"""The ``nd signal`` command: send a signal to a running task."""

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
from nd.commands._orchestration import request_all
from nd.nomad import NomadClient, NomadConfig
from nd.targets import ResolvedTarget, resolve_alloc_task, resolve_task_in_every_alloc
from nd.ui.text import plural, short_id

# The names every Nomad driver's SignalTask parses (consul-template's SignalLookup).
# Deriving this from the local libc instead diverges both ways: it drops SIGNULL and
# SIGIOT, which Nomad takes, and admits SIGCHLD and SIGURG, which Nomad deliberately
# refuses, turning a usage error back into the opaque driver error this check avoids.
_VALID_SIGNALS = frozenset(
    {
        "SIGABRT",
        "SIGALRM",
        "SIGBUS",
        "SIGCONT",
        "SIGFPE",
        "SIGHUP",
        "SIGILL",
        "SIGINT",
        "SIGIO",
        "SIGIOT",
        "SIGKILL",
        "SIGNULL",
        "SIGPIPE",
        "SIGPROF",
        "SIGQUIT",
        "SIGSEGV",
        "SIGSTOP",
        "SIGSYS",
        "SIGTERM",
        "SIGTRAP",
        "SIGTSTP",
        "SIGTTIN",
        "SIGTTOU",
        "SIGUSR1",
        "SIGUSR2",
        "SIGWINCH",
        "SIGXCPU",
        "SIGXFSZ",
    }
)

# Named when the allocation prompt cannot be shown, such as from cron
_ALLOC_PROMPT_REMEDY = "pass --all-allocs, or --alloc with an allocation ID"

app = command_app()


def _normalize_signal(value: str) -> str:
    """Resolve a user-typed signal name to the canonical name Nomad expects.

    Accept any case, with or without the ``SIG`` prefix, so ``usr1`` and ``SIGUSR1``
    both reach Nomad as ``SIGUSR1``. Validating against the names Nomad itself accepts
    turns a typo into a usage error before any request is sent, instead of an opaque
    driver error from Nomad.

    Returns:
        str: The canonical, ``SIG``-prefixed uppercase signal name.

    Raises:
        typer.BadParameter: If the value names no known signal.
    """
    name = value.strip().upper()
    if not name.startswith("SIG"):
        name = f"SIG{name}"
    if name not in _VALID_SIGNALS:
        valid = ", ".join(sorted(_VALID_SIGNALS))
        msg = f"unknown signal '{value}'; expected one of: {valid}"
        raise typer.BadParameter(msg)
    return name


@app.callback(invoke_without_command=True)
def signal(  # noqa: PLR0913
    ctx: typer.Context,
    # Declared before JOB only because a required parameter cannot follow a defaulted
    # one; JOB is still the sole positional.
    signal_name: Annotated[
        str,
        typer.Option("--signal", "-s", help="Signal to send, e.g. SIGUSR1. Case-insensitive."),
    ],
    job: Annotated[
        str | None,
        typer.Argument(
            help="Running job to signal; matches any job whose name contains this. "
            "Omit to pick from a list."
        ),
    ] = None,
    task: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Target task; skips the task prompt."),
    ] = None,
    alloc: Annotated[
        str | None,
        typer.Option(
            "--alloc",
            help="Allocation whose ID starts with this; skips the allocation prompt.",
        ),
    ] = None,
    all_allocs: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--all-allocs",
            help="Signal the task in every running allocation of the job; skips the "
            "allocation prompt.",
        ),
    ] = False,
    dry_run: Annotated[  # noqa: FBT002
        bool, dry_run_option("Show the target that would be signaled.")
    ] = False,
    verbose: VerboseOption = 0,
) -> None:
    """Send a signal to a running task.

    Resolves a running job, allocation, and task, prompting only where the choice is
    ambiguous, then delivers the signal. Use it to trigger an action a task exposes
    out of band, such as making a scheduled backup run now. When the job has several
    running allocations, --all-allocs signals every one, which suits scripts and cron
    because it does not depend on allocation IDs that change on each deploy.

    A success line means Nomad delivered the signal, not that the process acted on it.
    Check the task's logs to see what it did.
    """
    verbose = configure_verbosity(ctx, verbose)
    sig = _normalize_signal(signal_name)
    if alloc is not None and all_allocs:
        msg = (
            f"--all-allocs signals every allocation, so it cannot be combined with --alloc {alloc}"
        )
        raise typer.BadParameter(message=msg, param_hint="--all-allocs")
    config = NomadConfig.resolve()
    if not all_allocs:
        asyncio.run(
            _run(
                config=config,
                job=job,
                task=task,
                alloc=alloc,
                sig=sig,
                dry_run=dry_run,
                verbose=verbose,
            )
        )
        return
    exit_code = asyncio.run(
        _run_every_alloc(config=config, job=job, task=task, sig=sig, dry_run=dry_run)
    )
    if exit_code != 0:
        raise typer.Exit(exit_code)


def _describe(target: ResolvedTarget) -> str:
    """Name a signal target for output lines."""
    return f"task {target.task} in alloc {short_id(target.alloc_id)} ({target.job_name})"


async def _run(
    *,
    config: NomadConfig,
    job: str | None,
    task: str | None,
    alloc: str | None,
    sig: str,
    dry_run: bool,
    verbose: int,
) -> None:
    """Resolve a live target and signal it, sharing one client between both steps."""
    async with NomadClient(config) as client:
        target = await resolve_alloc_task(
            client=client,
            job_arg=job,
            task_arg=task,
            alloc_arg=alloc,
            alloc_remedy=_ALLOC_PROMPT_REMEDY,
            running_only=True,
        )
        if target is None:
            return

        where = _describe(target)
        if dry_run:
            pp.dryrun(f"Would send {sig} to {where}")
            return

        with pp.step(f"Sending {sig} to {target.task}") as step:
            await record_step(
                client.allocations.signal(target.alloc_id, signal=sig, task=target.task),
                step=step,
                verbose=verbose,
                method="POST",
                path=f"/client/allocation/{target.alloc_id}/signal",
            )

    pp.success(
        f"Sent {sig} to {where}",
        details=[f"run `nd logs {target.job_name}` to see what the task did"],
    )


async def _run_every_alloc(
    *, config: NomadConfig, job: str | None, task: str | None, sig: str, dry_run: bool
) -> int:
    """Signal one task in every running allocation of a job, reporting each delivery.

    A failed delivery to one allocation does not stop the others.

    Returns:
        int: The exit code: 1 when any delivery failed, else 0.
    """
    async with NomadClient(config) as client:
        targets = await resolve_task_in_every_alloc(client=client, job_arg=job, task_arg=task)
        if targets is None:
            return 0

        if dry_run:
            pp.dryrun(
                f"Would send {sig} to {plural(len(targets), 'task')}",
                details=[_describe(t) for t in targets],
            )
            return 0

        async def send(target: ResolvedTarget) -> str:
            await client.allocations.signal(target.alloc_id, signal=sig, task=target.task)
            pp.debug(f"POST /v1/client/allocation/{target.alloc_id}/signal")
            return ""

        exit_code = await request_all(
            items=targets,
            request=send,
            name_of=_describe,
            summary_of=lambda count: f"Sent {sig} to {plural(count, 'task')}",
            fail_verb=f"receive {sig}",
        )

    if exit_code == 0:
        pp.info(f"run `nd logs {targets[0].job_name}` to see what the tasks did")
    return exit_code
