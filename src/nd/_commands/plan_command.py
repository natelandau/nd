"""Plan a Nomad job."""
from pathlib import Path

from rich import print
from rich.table import Table

from nd._utils import list_valid_jobs
from nd._utils.alerts import logger as log


def plan_nomad_job(
    verbosity: int, dry_run: bool, log_to_file: bool, log_file: Path, config: dict, job_name: str
) -> bool:
    """Plan a Nomad job."""
    directories_to_search = config["job_files_locations"]

    try:
        valid_job_files = list_valid_jobs(directories_to_search, job_name)
    except AssertionError as e:
        log.error(e)  # noqa: TC400
        return False

    table = Table(title="Planned jobs", caption=f"{len(valid_job_files)} jobs planned")
    table.add_column("Job Name", justify="right", style="bold")
    table.add_column("Run Command", style="cyan")
    for job_to_plan in valid_job_files:
        run_command = f"nomad job run -check-index {job_to_plan.plan()} {job_to_plan.file}"
        table.add_row(job_to_plan.name, run_command)

    print(table)

    return True
