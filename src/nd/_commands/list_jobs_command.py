"""List command."""

from pathlib import Path

from rich import box, print
from rich.table import Table

from nd._commands.utils import list_valid_jobs
from nd._commands.utils.alerts import logger as log


def show_jobs(
    verbosity: int,
    dry_run: bool,
    log_to_file: bool,
    log_file: Path,
    config: dict,
    job_name: str | None = None,
) -> bool:
    """List command."""
    log.trace(config)

    directories_to_search = config["job_files_locations"]
    try:
        valid_job_files = list_valid_jobs(directories_to_search, job_name)
    except AssertionError as e:
        log.error(e)  # noqa: TC400
        return False

    log.info(f"Found {len(valid_job_files)} valid job files.")

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
