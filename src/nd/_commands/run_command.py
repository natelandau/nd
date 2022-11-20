"""Run a Nomad job."""

from pathlib import Path

from rich import print
from rich.progress import Progress, SpinnerColumn, TextColumn

from nd._utils import alerts, list_valid_jobs, select_one
from nd._utils.alerts import logger as log


def run_nomad_job(
    verbosity: int, dry_run: bool, log_to_file: bool, log_file: Path, config: dict, job_name: str
) -> bool:
    """Run a Nomad job."""
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
        try:  # pragma: no cover
            valid_job_files = list_valid_jobs(directories_to_search, job_name)
        except AssertionError as e:
            log.error(e)  # noqa: TC400
            return False

    if len(valid_job_files) == 0:
        log.error(f"No jobs files found matching {job_name}")
        return False

    if len(valid_job_files) > 1:
        print(f"Multiple jobs files found matching {job_name}")
        job = select_one(valid_job_files)
    else:
        job = valid_job_files[0]

    if job.run():
        alerts.success(f"{job.name} has been started.")
        return True

    return False
