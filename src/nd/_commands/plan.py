"""Plan a Nomad job."""
from pathlib import Path

from rich import print
from rich.table import Table

from nd._commands.utils import job_files
from nd._commands.utils.alerts import logger as log


def plan(
    verbosity: int, dry_run: bool, log_to_file: bool, log_file: Path, config: dict, job_name: str
) -> bool:
    """Plan a Nomad job."""
    directories_to_search = config["job_files_locations"]

    try:
        valid_job_files = job_files.list_job_files(directories_to_search, job_name)
    except AssertionError as e:
        log.error(e)
        return False

    table = Table(title="Planned jobs")
    table.add_column("Job Name", justify="right", style="bold")
    table.add_column("Run Command", style="cyan")
    for job_to_plan in valid_job_files:
        run_command = f"nomad job run -check-index {job_to_plan.plan()} {job_to_plan.file}"
        table.add_row(job_to_plan.name, run_command)

    print(table)

    return True
