"""Root Typer application and process entry point for the ``nd`` CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import typer
from nclutils import pp

from nd import __version__
from nd.commands import clean, exec, logs, plan, run, status, stop, volume  # noqa: A004
from nd.commands import list as list_cmd
from nd.nomad import (
    NomadAuthError,
    NomadConfigError,
    NomadConnectionError,
    NomadError,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(status.app, name="status")
app.add_typer(stop.app, name="stop")
app.add_typer(clean.app, name="clean")
app.add_typer(list_cmd.app, name="list")
app.add_typer(plan.app, name="plan")
app.add_typer(run.app, name="run")
app.add_typer(logs.app, name="logs")
app.add_typer(exec.app, name="exec")
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


@app.callback()
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
    """Run nd, a friendly wrapper around the Nomad API."""
    pp.configure(verbosity=verbose)
    ctx.obj = AppState(verbose=verbose)


def main() -> None:
    """Run the CLI, mapping Nomad client errors to clean, non-zero exits."""
    try:
        app()
    except KeyboardInterrupt as exc:
        # 130 = 128 + SIGINT(2), the conventional shell exit code for Ctrl-C.
        pp.warning("Aborted")
        raise SystemExit(130) from exc
    except NomadConnectionError as exc:
        pp.error("Could not reach the Nomad agent", details=[str(exc)])
        raise SystemExit(1) from exc
    except NomadAuthError as exc:
        pp.error("Not authorized by Nomad (check NOMAD_TOKEN)", details=[str(exc)])
        raise SystemExit(1) from exc
    except NomadConfigError as exc:
        pp.error("Invalid Nomad configuration", details=[str(exc)])
        raise SystemExit(1) from exc
    except NomadError as exc:
        pp.error("Nomad request failed", details=[str(exc)])
        raise SystemExit(1) from exc
