"""The ``nd exec`` command: open an interactive shell or run a command in a running task."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Annotated

import typer
from typer.core import TyperGroup

from nd.commands._common import VerboseOption, configure_verbosity, run_alloc_action
from nd.constants import DEFAULT_EXEC_SHELL, EXEC_SHELL_PROBE
from nd.nomad import NomadConfig

if TYPE_CHECKING:
    from typer._click import Context as ClickContext

# Where the ExecGroup stashes the post-`--` argv for the callback to read back.
CONTAINER_ARGV_KEY = "nd.exec.container_argv"


class ExecGroup(TyperGroup):
    """Split ``-- COMMAND...`` off argv before Click assigns positionals.

    Click consumes ``--`` as an end-of-options marker and then fills positionals in
    order, so ``nd exec -- ps`` would bind "ps" to JOB and leave the job picker
    unreachable. Removing the tail first keeps JOB genuinely optional in command mode.
    """

    def parse_args(self, ctx: ClickContext, args: list[str]) -> list[str]:
        """Stash everything after the first ``--``, then parse only what precedes it."""
        if "--" in args:
            index = args.index("--")
            ctx.meta[CONTAINER_ARGV_KEY] = args[index + 1 :]
            args = args[:index]
        return super().parse_args(ctx, args)


# allow_interspersed_args lets options follow the positional JOB (e.g. `nd exec web -s sh`).
app = typer.Typer(cls=ExecGroup, context_settings={"allow_interspersed_args": True})


def _container_command(shell: str | None, command: list[str] | None) -> list[str]:
    """Build the in-container argv: an explicit command, an explicit shell, or the probe.

    A command from ``-- COMMAND...`` runs verbatim, with no shell wrapping, so quoting
    and redirection stay the caller's business. An explicit ``--shell`` is run verbatim.
    With neither, probe for bash inside the container and fall back to sh so the nicer
    shell is used when present without failing on minimal images that ship only sh.
    """
    if command:
        return command
    if shell is not None:
        return [shell]
    return [DEFAULT_EXEC_SHELL, "-c", EXEC_SHELL_PROBE]


def _wants_tty(*, no_tty: bool) -> bool:
    """Decide whether to request a pseudo-terminal for this session.

    Both shell and command mode require stdin and stdout to both be terminals. Nomad
    cannot attach a pseudo-terminal to a redirected or piped stream, so requesting one
    there is a guaranteed failure rather than a preference; `echo ls | nd exec web`
    still works because stdin is already not a tty in that case.
    """
    if no_tty:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


@app.callback(invoke_without_command=True)
def exec_(
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(
            help="Running job to enter; matches any job whose name contains this. "
            "Omit to pick from a list. Must come before `--` when running a command."
        ),
    ] = None,
    task: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Target task; skips the task prompt."),
    ] = None,
    shell: Annotated[
        str | None,
        typer.Option(
            "--shell", "-s", help="Shell to launch (default: bash, or sh if bash is absent)."
        ),
    ] = None,
    no_tty: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--no-tty", "-T", help="Do not allocate a pseudo-terminal."),
    ] = False,
    verbose: VerboseOption = 0,
) -> None:
    """Open an interactive shell inside a running task, or run one command in it.

    Resolves a running job, allocation, and task, prompting only where the choice is
    ambiguous, then runs a shell or command over nomad alloc exec. With no --shell and
    no `-- COMMAND`, it prefers bash and falls back to sh, so it works on minimal images.

    Anything after `--` runs as a command instead of opening a shell, passed to the
    container verbatim with no shell wrapping. Use `-- sh -c '...'` when you want pipes
    or redirection inside the container.
    """
    configure_verbosity(ctx, verbose)
    command = ctx.meta.get(CONTAINER_ARGV_KEY)
    if command is not None and not command:
        msg = "no command given after `--`"
        raise typer.BadParameter(msg)
    if command and shell is not None:
        msg = "--shell cannot be combined with a `-- COMMAND`; use `-- <shell> -c ...` instead"
        raise typer.BadParameter(msg)
    config = NomadConfig.resolve()
    container_command = _container_command(shell, command)
    run_alloc_action(
        config,
        job=job,
        task=task,
        running_only=True,
        action=lambda nomad, alloc_id, task_name: nomad.exec_command(
            alloc_id, task_name, container_command, tty=_wants_tty(no_tty=no_tty)
        ),
    )
