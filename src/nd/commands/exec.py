"""The ``nd exec`` command: open an interactive shell inside a running task."""

from __future__ import annotations

from typing import Annotated

import typer

from nd.commands._common import VerboseOption, configure_verbosity, run_alloc_action
from nd.constants import DEFAULT_EXEC_SHELL, EXEC_SHELL_PROBE
from nd.nomad import NomadConfig

# allow_interspersed_args lets options follow the positional JOB (e.g. `nd exec web -s sh`).
app = typer.Typer(context_settings={"allow_interspersed_args": True})


def _container_command(shell: str | None) -> list[str]:
    """Build the in-container argv: an explicit shell, or bash-with-sh fallback.

    An explicit ``--shell`` is run verbatim. With no flag, probe for bash inside the
    container and fall back to sh so the nicer shell is used when present without
    failing on minimal images that ship only sh.
    """
    if shell is not None:
        return [shell]
    return [DEFAULT_EXEC_SHELL, "-c", EXEC_SHELL_PROBE]


@app.callback(invoke_without_command=True)
def exec_(
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(help="Running job to enter; matches any job whose name starts with this."),
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
    verbose: VerboseOption = 0,
) -> None:
    """Open an interactive shell inside a running task's allocation."""
    configure_verbosity(ctx, verbose)
    config = NomadConfig.resolve()
    command = _container_command(shell)
    run_alloc_action(
        config,
        job=job,
        task=task,
        running_only=True,
        action=lambda nomad, alloc_id, task_name: nomad.exec_shell(alloc_id, task_name, command),
    )
