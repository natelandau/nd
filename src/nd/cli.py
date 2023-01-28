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

from nd import _commands, _utils
from nd._utils.alerts import logger as log

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich")

typer.rich_utils.STYLE_HELPTEXT = ""


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
    """Load configuration data from toml file. If not found, return default config.

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
                    log.exception(f"Could not parse '{config_file}'")
                    raise typer.Exit(code=1) from e
            break

    if not config:
        log.error("No configuration found. Please create a config file.")
        raise typer.Exit(code=1)

    if config.get("job_files_locations") is None:
        log.error(
            "Configuration file is missing 'job_files_locations' key. "
            "Please check your configuration file."
        )
        raise typer.Exit(code=1)

    if config.get("nomad_api_url") is None:
        log.error(
            "Configuration file is missing 'nomad_api_url' key. "
            "Please check your configuration file."
        )
        raise typer.Exit(code=1)

    if not validators.url(config["nomad_api_url"]):
        log.error(
            "Configuration file 'nomad_api_url' is not a valid URL. "
            "Please check your configuration file."
        )
        raise typer.Exit(code=1)

    return config


@app.command(short_help="Run Nomad garbage collection.")
def clean() -> None:
    """[bold]Run Nomad garbace collection[/bold].

    Nomad periodically garbage collects jobs, evaluations, allocations, and nodes. The exact garbage collection logic varies by object, but in general Nomad only permanently deletes objects once they are terminal and no longer needed for future scheduling decisions.

    This command bypasses these settings and immediately attempts to garbage collect dead objects regardless of any "threshold" or "interval" server settings. This is useful to quickly free memory on servers running low, but users should prefer tuning periodic garbage collection parameters to meet their needs instead of relying on manually running garbage collection.
    """
    if not _commands.run_garbage_collection(
        state.verbosity,
        state.dry_run,
        state.log_to_file,
        state.log_file,
        state.config,
    ):
        raise typer.Exit(1)


@app.command(
    "exec", short_help="Run a command or enter an interactive shell within a running container."
)
def exec_in_container(
    task_name: str = typer.Argument(
        ...,
        help="Name or partial name of a task to run command in.",
        show_default=False,
    ),
    exec_command: Optional[str] = typer.Argument(
        "/bin/sh", help="Command to run in the container.", show_default=True
    ),
) -> None:
    """[bold]Run a command or enter an interactive shell within a running container[/bold].

    Command to enter an interactive shell within a running container is printed to the screen and copied to your clipboard.

    [underline]Example Usage[/underline]

       [dim]# Default brings up an interactive shell (/bin/sh)[/dim]
       nd exec webserver

       [dim]# Specify a shell[/dim]
       nd exec webserver /bin/bash

       [dim]# Run a command[/dim]
       nd exec webserver "/bin/bash -c 'ls -la'"
    """
    if not _commands.exec_in_container(
        state.verbosity,
        state.dry_run,
        state.log_to_file,
        state.log_file,
        state.config,
        task_name,
        exec_command,
    ):
        raise typer.Exit(1)


@app.command(short_help="Run a Nomad job.")
def run(
    job_name: str = typer.Argument(
        ...,
        help="Name or partial name of a Nomad job to run.",
        show_default=False,
    )
) -> None:
    """[bold]Run a Nomad job[/bold].

    If the allocation is already running, you will be prompted before replacing the allocation with a new instance.
    """
    if not _commands.run_nomad_job(
        state.verbosity, state.dry_run, state.log_to_file, state.log_file, state.config, job_name
    ):
        raise typer.Exit(1)


@app.command(short_help="Stop a running Nomad job.")
def stop(
    job_name: str = typer.Argument(
        ...,
        help="Name or partial name of a Nomad job to stop.",
        show_default=False,
    ),
    no_clean: bool = typer.Option(
        False,
        "--no-clean",
        help="Do not garbage collect the job after stopping.",
    ),
) -> None:
    """[bold]Stop a running job[/bold].

    If the specified job is running, the job will be stopped and garbage collected. To prevent garbage collection, use the [bold]--no-clean[/bold] flag.
    """
    if not _commands.stop_job(
        state.verbosity,
        state.dry_run,
        state.log_to_file,
        state.log_file,
        state.config,
        job_name,
        no_clean,
    ):
        raise typer.Exit(1)


@app.command(short_help="Stop, garbage collect, and rerun selected Nomad Job.")
def update(
    job_name: str = typer.Argument(
        ...,
        help="Name or partial name of a Nomad job to rebuild.",
        show_default=False,
    ),
) -> None:
    """[bold]Stop, garbage collect, and run selected Nomad Job[/bold].

    [blue]update[/blue] command automates a common task of:

    1. Stopping a running job
    2. Garbage collecting the job
    3. Running the job again
    """
    if _commands.stop_job(
        state.verbosity,
        state.dry_run,
        state.log_to_file,
        state.log_file,
        state.config,
        job_name,
        no_clean=False,
    ):
        if not _commands.run_nomad_job(
            state.verbosity,
            state.dry_run,
            state.log_to_file,
            state.log_file,
            state.config,
            job_name,
        ):
            raise typer.Exit(1)
    else:
        raise typer.Exit(1)


@app.command(short_help="Plan a Nomad job.")
def plan(
    job_name: str = typer.Argument(
        ...,
        help="Name or partial name of a Nomad job to plan.",
        show_default=False,
    )
) -> None:
    """[bold]Plans a Nomad job[/bold].

    Pass a complete or partial job name to run all matching jobs.

    Returns the Nomad Job Run command to start the job.
    """
    if not _commands.plan_nomad_job(
        state.verbosity, state.dry_run, state.log_to_file, state.log_file, state.config, job_name
    ):
        raise typer.Exit(1)


@app.command(short_help="View the running logs from a task.")
def logs(
    task_name: str = typer.Argument(
        ...,
        help="Name or partial name of a task to view logs for.",
        show_default=False,
    )
) -> None:
    """[bold]View the running logs from a task[/bold].

    Will print the command to run to view logs and copy it to your clipboard.
    """
    if not _commands.view_logs(
        state.verbosity,
        state.dry_run,
        state.log_to_file,
        state.log_file,
        state.config,
        task_name,
    ):
        raise typer.Exit(1)


@app.command(short_help="Show status of Nomad cluster.")
def status() -> None:
    """Show status of Nomad cluster."""
    if not _commands.show_cluster_status(
        state.verbosity, state.dry_run, state.log_to_file, state.log_file, state.config
    ):
        raise typer.Exit(1)


@app.command("list", short_help="List all valid Nomad job files.")
def list_jobs(
    job_name: Optional[str] = typer.Argument(
        None,
        help="Name or partial name of a Nomad jobs to list.",
        show_default=False,
    ),
    filter_running: bool = typer.Option(
        False,
        "--filter-running/--running",
        help="Filter results to only show jobs that are not running.",
        show_default=True,
    ),
) -> None:
    """[bold]List all valid Nomad jobs files[/bold].

    Pass a complete or partial job name to list all matching job files.
    """
    if not _commands.list_jobs_command.show_jobs(
        state.verbosity,
        state.dry_run,
        state.log_to_file,
        state.log_file,
        state.config,
        job_name,
        filter_running,
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
        Path(Path.home() / "logs" / "nd.log"),
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
    """Light wrapper around common Nomad API commands and tasks.

    Full usage and help: https://github.com/natelandau/nd
    """
    possible_config_locations = (
        [config_file]
        if config_file
        else [
            Path.home() / ".config" / "nd.toml",
            Path.home() / ".nd" / "nd.toml",
            Path.home() / ".nd.toml",
            Path.cwd() / "nd.toml",
            Path.cwd() / ".nd.toml",
        ]
    )

    # Instantiate logger manager
    _utils.alerts.LoggerManager(  # pragma: no cover
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
