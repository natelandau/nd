"""List command."""

from pathlib import Path

from rich import box, print
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from nd._commands.utils import list_valid_jobs, populate_running_jobs
from nd._commands.utils.alerts import logger as log


def show_jobs(  # noqa: C901
    verbosity: int,
    dry_run: bool,
    log_to_file: bool,
    log_file: Path,
    config: dict,
    job_name: str | None = None,
    not_running: bool = False,
) -> bool:
    """List command."""
    log.trace(config)

    directories_to_search = config["job_files_locations"]

    if verbosity <= 1:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            progress.add_task(description="Processing job files...", total=None)
            try:
                valid_job_files = list_valid_jobs(directories_to_search, job_name)
            except AssertionError as e:
                progress.stop()
                log.error(e)  # noqa: TC400
                return False
    else:
        try:
            valid_job_files = list_valid_jobs(directories_to_search, job_name)
        except AssertionError as e:
            log.error(e)  # noqa: TC400
            return False

    if not_running:
        running_jobs = populate_running_jobs(config["nomad_api_url"])
        if len(running_jobs) > 0:
            for running_job in running_jobs:
                for job in valid_job_files:
                    if job.name in running_job.job_id:
                        valid_job_files.remove(job)
                        break

    table = Table(
        caption=f"{len(valid_job_files)} valid Nomad jobs found.",
        box=box.DOUBLE_EDGE,
        show_edge=True,
        show_lines=False,
        highlight=True,
    )

    table.add_column("Job", justify="left")
    table.add_column("Path", justify="left")
    if verbosity > 1:
        table.add_column("Local Backup", justify="left", style="#c6c6c6")
    for job in sorted(valid_job_files, key=lambda x: x.name):
        if verbosity > 1:
            table.add_row(job.name, str(job.file), str(job.local_backup))
        else:
            table.add_row(job.name, str(job.file))

    print(table)
    return True
