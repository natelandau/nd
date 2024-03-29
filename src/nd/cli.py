"""nd CLI."""

import shutil
from pathlib import Path
from typing import Annotated, Optional

import typer
from confz import validate_all_configs
from loguru import logger

from nd.__version__ import __version__
from nd.config import NDConfig
from nd.constants import CONFIG_PATH, NDObject
from nd.models.nomad_api import NomadAPI
from nd.utils import alerts, instantiate_logger
from nd.utils.console import console
from nd.utils.helpers import (
    find_job_files,
    find_nodes,
    find_running_jobs,
    print_status_table,
    print_table,
)
from nd.utils.questions import select_one

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

typer.rich_utils.STYLE_HELPTEXT = ""


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"{__package__} version: {__version__}")
        raise typer.Exit()


@app.command(short_help="Run Nomad garbage collection.")
def clean() -> None:
    """[bold]Run Nomad garbace collection[/bold].

    Nomad periodically garbage collects jobs, evaluations, allocations, and nodes. The exact garbage collection logic varies by object, but in general Nomad only permanently deletes objects once they are terminal and no longer needed for future scheduling decisions.

    This command bypasses these settings and immediately attempts to garbage collect dead objects regardless of any "threshold" or "interval" server settings. This is useful to quickly free memory on servers running low, but users should prefer tuning periodic garbage collection parameters to meet their needs instead of relying on manually running garbage collection.
    """
    api = NomadAPI(NDConfig().nomad_address)

    if api.garbage_collect():
        logger.success("Garbage collection complete")
    else:
        logger.error("Garbage collection failed")
        raise typer.Exit(1)


@app.command(
    "exec", short_help="Run a command or enter an interactive shell within a running container."
)
def exec_in_container(
    job_name: str = typer.Argument(
        ...,
        help="Name or partial name of a job to run command in.",
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
    api = NomadAPI(NDConfig().nomad_address)
    running_jobs = find_running_jobs(
        api,
        filter_pattern=job_name,
        dry_run=NDConfig().dry_run,
        nomad_address=NDConfig().nomad_address,
    )
    job = select_one(running_jobs, nd_object=NDObject.RUNNING_JOB, search_term=job_name)

    task = select_one(
        [t for alloc in job.allocations for t in alloc.tasks], nd_object=NDObject.TASK
    )

    task.execute(exec_command)


@app.command("list", short_help="List all valid Nomad job files.")
def list_job_files(
    job_name: Optional[str] = typer.Argument(
        None,
        help="Name or partial name of a Nomad jobs to list.",
        show_default=False,
    ),
) -> None:
    """List all valid Nomad job files."""
    api = NomadAPI(NDConfig().nomad_address)

    running_jobs = find_running_jobs(
        api,
        filter_pattern=job_name,
        dry_run=NDConfig().dry_run,
        nomad_address=NDConfig().nomad_address,
    )
    job_files = find_job_files(search_string=job_name)
    print_table(
        title=f"Valid Nomad Job Files matching '{job_name}'"
        if job_name
        else "Valid Nomad Job Files",
        columns=["", "Name", "Path"],
        rows=[
            [
                ":white_check_mark:" if job.name in [j.name for j in running_jobs] else None,
                job.name,
                str(job.path),
                "style:bold" if job.name in [j.name for j in running_jobs] else "style:None",
            ]
            for job in job_files
        ],
        footer=f"Found {len(job_files)} job files.",
    )


@app.command(short_help="View the running logs from a task.")
def logs(
    job_name: str = typer.Argument(
        ...,
        help="Name or partial name of a Nomad job to plan.",
        show_default=False,
    ),
) -> None:
    """[bold]View the running logs from a task[/bold].

    Will print the command to run to view logs and copy it to your clipboard.
    """
    api = NomadAPI(NDConfig().nomad_address)
    running_jobs = find_running_jobs(
        api,
        filter_pattern=job_name,
        dry_run=NDConfig().dry_run,
        nomad_address=NDConfig().nomad_address,
    )
    job = select_one(running_jobs, nd_object=NDObject.RUNNING_JOB, search_term=job_name)

    task = select_one(
        [t for alloc in job.allocations for t in alloc.tasks], nd_object=NDObject.TASK
    )

    task.logs()


@app.command(short_help="Plan a Nomad job.")
def plan(
    job_name: str = typer.Argument(
        ...,
        help="Name or partial name of a Nomad job to plan.",
        show_default=False,
    ),
) -> None:
    """[bold]Plan a Nomad job[/bold].

    Pass a complete or partial job name to run all matching jobs.

    Returns the Nomad Job Run command to start the job.
    """
    job_files = find_job_files(search_string=job_name)

    print_table(
        title="Nomad Run Commands",
        columns=["Name", "Run Command"],
        footer=f"Found {len(job_files)} job files.",
        rows=[
            [job.name, f"nomad job run -check-index {index_id} {job.path}"]
            for job in job_files
            if (index_id := job.plan()) is not None
        ],
    )


@app.command(short_help="Run a Nomad job.")
def run(
    job_name: str = typer.Argument(
        ...,
        help="Name or partial name of a Nomad job to run.",
        show_default=False,
    ),
) -> None:
    """[bold]Run a Nomad job[/bold].

    If the allocation is already running, you will be prompted before replacing the allocation with a new instance.
    """
    api = NomadAPI(NDConfig().nomad_address)
    running_jobs = find_running_jobs(
        api,
        filter_pattern=job_name,
        dry_run=NDConfig().dry_run,
        nomad_address=NDConfig().nomad_address,
    )
    job_files = find_job_files(search_string=job_name, api=api)
    job_file = select_one(job_files, nd_object=NDObject.JOBFILE, search_term=job_name)

    if job_file.name in [j.name for j in running_jobs]:
        alerts.info(f"Job '{job_file.name}' is already running")
        raise typer.Exit(0)

    if job_file.run():
        logger.success(f"Job '{job_file.name}' started")
    else:
        logger.error(f"Job '{job_file.name}' failed to start")
        raise typer.Exit(1)


@app.command(short_help="Show status of Nomad cluster.")
def status() -> None:
    """Show status of Nomad cluster."""
    api = NomadAPI(NDConfig().nomad_address)
    running_jobs = find_running_jobs(
        api, dry_run=NDConfig().dry_run, nomad_address=NDConfig().nomad_address
    )
    nodes = find_nodes(api)
    print_status_table(nodes, running_jobs, nomad_address=NDConfig().nomad_address)


@app.command(short_help="Stop a running job.")
def stop(
    job_name: str = typer.Argument(
        ...,
        help="Name or partial name of a Nomad job to stop.",
        show_default=False,
    ),
    no_clean: bool = typer.Option(  # noqa: ARG001
        False,
        "--no-clean",
        help="Do not garbage collect the job after stopping.",
    ),
) -> None:
    """[bold]Stop a running job[/bold].

    If the specified job is running, the job will be stopped and garbage collected. To prevent garbage collection, use the [bold]--no-clean[/bold] flag.
    """
    api = NomadAPI(NDConfig().nomad_address, dry_run=NDConfig().dry_run)
    running_jobs = find_running_jobs(
        api,
        filter_pattern=job_name,
        dry_run=NDConfig().dry_run,
        nomad_address=NDConfig().nomad_address,
    )

    select_one(running_jobs, nd_object=NDObject.RUNNING_JOB, search_term=job_name).stop()


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
    api = NomadAPI(NDConfig().nomad_address, dry_run=NDConfig().dry_run)
    running_jobs = find_running_jobs(
        api,
        filter_pattern=job_name,
        dry_run=NDConfig().dry_run,
        nomad_address=NDConfig().nomad_address,
    )
    job_files = find_job_files(search_string=job_name, api=api)

    if len(running_jobs) == 0 or len(job_files) == 0:
        logger.error(f"No running jobs found matching '{job_name}' Exiting.")
        raise typer.Exit(0)

    running_job = select_one(running_jobs, nd_object=NDObject.RUNNING_JOB, search_term=job_name)

    if not running_job.stop():
        logger.error(f"Job '{running_job.name}' failed to stop")
        raise typer.Exit(1)

    job_file = [x for x in job_files if x.name == running_job.name]
    if len(job_file) == 0 or len(job_file) > 1:
        logger.error(f"Job file not found for '{running_job.name}'")
        raise typer.Exit(1)
    if job_file[0].run():
        logger.success(f"Job '{job_file[0].name}' started")
    else:
        logger.error(f"Job '{job_file[0].name}' failed to start")
        raise typer.Exit(1)


@app.callback()
def main(
    dry_run: Annotated[  # noqa: ARG001
        bool,
        typer.Option(
            "--dry-run",
            help="Dry run - don't actually change anything",
            show_default=True,
        ),
    ] = False,
    force: Annotated[  # noqa: ARG001
        bool,
        typer.Option(
            "--force",
            help="Force changes without prompting for confirmation. Use with caution!",
            show_default=True,
        ),
    ] = False,
    log_file: Annotated[
        Path,
        typer.Option(
            help="Path to log file",
            show_default=False,
            dir_okay=False,
            file_okay=True,
            exists=False,
        ),
    ] = Path(Path.home() / "logs" / f"{__package__}.log"),
    log_to_file: Annotated[
        Optional[bool],
        typer.Option(
            "--log-to-file",
            help="Log to file",
            show_default=True,
        ),
    ] = None,
    verbosity: Annotated[
        int,
        typer.Option(
            "-v",
            "--verbose",
            show_default=True,
            help="""Set verbosity level(0=INFO, 1=DEBUG, 2=TRACE)""",
            count=True,
        ),
    ] = 0,
    version: Annotated[  # noqa: ARG001
        Optional[bool],
        typer.Option(
            "--version",
            is_eager=True,
            callback=version_callback,
            help="Print version and exit",
        ),
    ] = None,
) -> None:
    """Light wrapper around common Nomad API commands and tasks.

    Full usage and help: https://github.com/natelandau/nd
    """
    # Instantiate Logging
    instantiate_logger(verbosity, log_file, log_to_file)

    validate_all_configs()

    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        default_config_file = Path(__file__).parent.resolve() / "default_config.toml"
        shutil.copy(default_config_file, CONFIG_PATH)
        alerts.success(f"Created default configuration file at {CONFIG_PATH}")
        alerts.notice(f"Please edit {CONFIG_PATH} before continuing")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
