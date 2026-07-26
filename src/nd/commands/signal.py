"""The ``nd signal`` command: send a signal to a running task."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from nclutils import pp

from nd.commands._common import VerboseOption, configure_verbosity, record_step
from nd.nomad import NomadClient, NomadConfig
from nd.targets import resolve_with_client

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

# allow_interspersed_args lets options follow the positional JOB (e.g. `nd signal web -s HUP`).
app = typer.Typer(context_settings={"allow_interspersed_args": True})


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
def signal(
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
    dry_run: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--dry-run", "-n", help="Show the target that would be signaled."),
    ] = False,
    verbose: VerboseOption = 0,
) -> None:
    """Send a signal to a running task.

    Resolves a running job, allocation, and task, prompting only where the choice is
    ambiguous, then delivers the signal. Use it to trigger an action a task exposes
    out of band, such as making a scheduled backup run now.

    A success line means Nomad delivered the signal, not that the process acted on it.
    Check the task's logs to see what it did.
    """
    verbose = configure_verbosity(ctx, verbose)
    sig = _normalize_signal(signal_name)
    config = NomadConfig.resolve()
    asyncio.run(_run(config, job=job, task=task, sig=sig, dry_run=dry_run, verbose=verbose))


async def _run(
    config: NomadConfig,
    *,
    job: str | None,
    task: str | None,
    sig: str,
    dry_run: bool,
    verbose: int,
) -> None:
    """Resolve a live target and signal it, sharing one client between both steps.

    Raises:
        typer.Exit: If an argument matches nothing selectable, or a needed prompt
            cannot be shown.
    """
    async with NomadClient.from_config(config) as client:
        exit_code, target = await resolve_with_client(
            client, job_arg=job, task_arg=task, running_only=True
        )
        if exit_code != 0:
            raise typer.Exit(exit_code)
        if target is None:
            return

        where = f"task {target.task} in alloc {target.alloc_id[:8]} ({target.job_name})"
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
