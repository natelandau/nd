"""nd CLI."""

from pathlib import Path
from typing import Optional

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore [no-redef]

import rich.repr
import typer
import validators

from nd import _commands
from nd._commands.utils.alerts import logger as log

# from rich import print


app = typer.Typer()


@rich.repr.auto
class State:
    """State of CLI. Holds all user defined flags for use within commands."""

    def __init__(
        self,
        verbosity: int,
        dry_run: bool,
        log_to_file: bool,
        log_file: Path,
        config: dict,
    ):
        self.verbosity = verbosity
        self.dry_run = dry_run
        self.log_to_file = log_to_file
        self.log_file = log_file
        self.config = config


state = State(0, False, False, Path(""), {})


def load_configuration(paths: list[Path]) -> dict:
    """
    Load configuration data from toml file. If not found, return default config.

    Args:
        paths: List of possible config locations.

    Returns:
        dict: Configuration data.

    Raises:
        Exit: If config file is malformed or not found
    """
    config = {}
    for config_file in paths:
        if config_file.exists():
            log.debug(f"Loading configuration from {config_file}")
            with open(config_file, mode="rb") as fp:
                try:
                    config = tomllib.load(fp)
                except tomllib.TOMLDecodeError as e:
                    log.error(f"Could not parse '{config_file}': {e}")
                    raise typer.Exit(code=1)
            break

    if not config:
        log.error("No configuration found. Please create a config file.")
        raise typer.Exit(code=1)
    elif config.get("job_files_locations") is None:
        log.error(
            "Configuration file is missing 'job_files_locations' key. "
            "Please check your configuration file."
        )
        raise typer.Exit(code=1)
    elif config.get("nomad_api_url") is None:
        log.error(
            "Configuration file is missing 'nomad_api_url' key. "
            "Please check your configuration file."
        )
        raise typer.Exit(code=1)
    elif not validators.url(config["nomad_api_url"]):
        log.error(
            "Configuration file 'nomad_api_url' is not a valid URL. "
            "Please check your configuration file."
        )
        raise typer.Exit(code=1)

    return config


@app.command()
def clean() -> None:
    """Say a message."""
    log.info("clean")


@app.command()
def exec() -> None:
    """Say a message."""
    log.info("exec")


@app.command()
def stop() -> None:
    """Say a message."""
    log.info("stop")


@app.command()
def start() -> None:
    """Say a message."""
    log.info("start")


@app.command()
def rebuild() -> None:
    """Say a message."""
    log.info("rebuild")


@app.command()
def plan() -> None:
    """Say a message."""
    log.info("plan")


@app.command()
def logs() -> None:
    """Say a message."""
    log.info("logs")


@app.command()
def status() -> None:
    """Say a message."""
    log.info("status")


@app.command("list")
def list_jobs(
    job_name: Optional[str] = typer.Argument(
        None,
        help="Name or partial name of a Nomad jobs to list.",
        show_default=False,
    )
) -> None:
    """List all valid Nomad jobs. Pass a complete or partial job name to list all matching jobs."""
    if not _commands.list_jobs(
        state.verbosity, state.dry_run, state.log_to_file, state.log_file, state.config, job_name
    ):
        raise typer.Exit(1)


@app.callback()
def main(
    verbosity: int = typer.Option(
        0,
        "-v",
        "--verbose",
        show_default=False,
        help="""Set verbosity level (0=WARN, 1=INFO, 2=DEBUG, 3=TRACE)""",
        count=True,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Dry run",
    ),
    log_to_file: bool = typer.Option(
        False,
        "--log-to-file",
        help="Log to file",
        show_default=True,
    ),
    log_file: Path = typer.Option(
        Path(Path.home() / "logs" / "halp.log"),
        help="Path to log file",
        show_default=True,
        dir_okay=False,
        file_okay=True,
        exists=False,
    ),
    config_file: Path = typer.Option(
        None,
        help="Specify a custom path to configuration file.",
        show_default=False,
        dir_okay=False,
        file_okay=True,
        exists=True,
    ),
) -> None:
    """Manage users in the awesome CLI app."""
    # Find a config file
    if config_file:  # pragma: no cover
        possible_config_locations = [config_file]
    else:
        possible_config_locations = [
            Path.home() / ".config" / "nd.toml",
            Path.home() / ".nd" / "nd.toml",
            Path.home() / ".nd.toml",
            Path.cwd() / "nd.toml",
            Path.cwd() / ".nd.toml",
        ]

    # Instantiate logger manager
    _commands.utils.alerts.LoggerManager(  # pragma: no cover
        log_file,
        verbosity,
        log_to_file,
    )

    state.verbosity = verbosity
    state.dry_run = dry_run
    state.log_to_file = log_to_file
    state.log_file = log_file
    state.config = load_configuration(possible_config_locations)


if __name__ == "__main__":
    app()
