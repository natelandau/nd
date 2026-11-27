"""Root Typer application and process entry point for the ``nd`` CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import typer
from nclutils import pp
from typer import _click as click  # Typer vendors Click; TyperGroup overrides take its Context
from typer.core import TyperGroup

from nd import __version__
from nd.commands import (
    clean,
    doctor,
    exec,  # noqa: A004
    logs,
    plan,
    restart,
    run,
    signal,
    status,
    stop,
    update,
    volume,
)
from nd.commands import list as list_cmd
from nd.nomad import (
    NomadAuthError,
    NomadConfigError,
    NomadConnectionError,
    NomadError,
)
from nd.targets import SelectionError
from nd.ui.prompts import PromptUnavailableError
from nd.ui.text import strip_terminal_controls

DEFAULT_SUBCOMMAND = "status"


class DefaultStatusGroup(TyperGroup):
    """Route options that no root flag claims to the default ``status`` subcommand.

    Bare ``nd`` already shows the status dashboard, so ``nd --hosts`` and ``nd --json``
    should too. Declaring those flags on the root would list them in global help and let
    ``nd run --hosts`` accept and ignore them, so they are forwarded here instead.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Insert ``status`` before the first argument that is an option the root lacks.

        Args:
            ctx: The root command's context.
            args: The raw command-line arguments after ``nd``.

        Returns:
            list[str]: The arguments left for the subcommand, as Typer returns them.
        """
        root_long_options: set[str] = set()
        root_short_flags: set[str] = set()
        for param in self.get_params(ctx):
            for option in (*param.opts, *param.secondary_opts):
                if option.startswith("--"):
                    root_long_options.add(option)
                elif option.startswith("-"):
                    root_short_flags.add(option[1:])

        def is_root_option(token: str) -> bool:
            if token.startswith("--"):
                return token in root_long_options
            # A bundled short flag such as -vv
            return (
                token.startswith("-")
                and len(token) > 1
                and all(flag in root_short_flags for flag in token[1:])
            )

        first_unclaimed = next(
            (index for index, token in enumerate(args) if not is_root_option(token)), None
        )
        if (
            first_unclaimed is not None
            and args[first_unclaimed].startswith("-")
            and args[first_unclaimed] != "--"
        ):
            args = [*args[:first_unclaimed], DEFAULT_SUBCOMMAND, *args[first_unclaimed:]]
        return super().parse_args(ctx, args)


app = typer.Typer(
    cls=DefaultStatusGroup,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(status.app, name="status")
app.add_typer(stop.app, name="stop")
app.add_typer(clean.app, name="clean")
app.add_typer(doctor.app, name="doctor")
app.add_typer(list_cmd.app, name="list")
app.add_typer(plan.app, name="plan")
app.add_typer(run.app, name="run")
app.add_typer(update.app, name="update")
app.add_typer(logs.app, name="logs")
app.add_typer(exec.app, name="exec")
app.add_typer(signal.app, name="signal")
app.add_typer(restart.app, name="restart")
app.add_typer(volume.app, name="volume")


@dataclass
class AppState:
    """Shared CLI state passed to subcommands via the Typer context object."""

    verbose: int = 0


def _version_callback(value: bool) -> None:  # noqa: FBT001
    """Print the version and exit when ``--version`` is passed."""
    if value:
        pp.console().print(f"nd {__version__}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    verbose: Annotated[
        int,
        typer.Option(
            "-v", "--verbose", count=True, help="Increase verbosity (-v debug, -vv trace)."
        ),
    ] = 0,
    version: Annotated[  # noqa: ARG001, FBT002
        bool,
        typer.Option(
            "--version",
            is_eager=True,
            callback=_version_callback,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Manage Nomad jobs, allocations, and host volumes from the command line.

    With no command, show the status dashboard. Status options such as --hosts and
    --json work here too.
    """
    pp.configure(verbosity=verbose)
    ctx.obj = AppState(verbose=verbose)

    # With no subcommand, default to the status dashboard rather than printing help.
    if ctx.invoked_subcommand is None:
        status.status(ctx, verbose=verbose)


def _run_app() -> None:
    """Run the CLI, raising a group of Nomad errors as its first error.

    A command that runs tasks in a task group fails with an exception group, while main()
    reports a bare Nomad error.
    """
    try:
        app()
    except BaseExceptionGroup as group:
        nomad_errors, others = group.split(NomadError)
        if nomad_errors is None or others is not None:
            raise
        error: BaseException = nomad_errors
        while isinstance(error, BaseExceptionGroup):
            error = error.exceptions[0]
        raise error from None


def _plain(error: BaseException) -> str:
    """Render an error as text with no terminal control sequences.

    Error messages carry names and response bodies from the cluster, such as job and task
    names, so an escape sequence in one could otherwise drive the user's terminal.
    """
    return strip_terminal_controls(str(error))


def main() -> None:
    """Run the CLI, mapping Nomad client errors to clean, non-zero exits."""
    try:
        _run_app()
    except KeyboardInterrupt as exc:
        # 130 = 128 + SIGINT(2), the conventional shell exit code for Ctrl-C.
        pp.warning("Aborted")
        raise SystemExit(130) from exc
    except (PromptUnavailableError, SelectionError) as exc:
        pp.error(_plain(exc))
        raise SystemExit(1) from exc
    except NomadConnectionError as exc:
        pp.error("Could not reach the Nomad agent", details=[_plain(exc)])
        raise SystemExit(1) from exc
    except NomadAuthError as exc:
        pp.error("Not authorized by Nomad (check NOMAD_TOKEN)", details=[_plain(exc)])
        raise SystemExit(1) from exc
    except NomadConfigError as exc:
        pp.error("Invalid Nomad configuration", details=[_plain(exc)])
        raise SystemExit(1) from exc
    except NomadError as exc:
        pp.error("Nomad request failed", details=[_plain(exc)])
        raise SystemExit(1) from exc
