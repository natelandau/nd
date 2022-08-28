"""Stop a running job."""
from pathlib import Path

from rich import print

from nd._utils import alerts, populate_running_jobs, select_one
from nd._utils.alerts import logger as log


def stop_job(
    verbosity: int,
    dry_run: bool,
    log_to_file: bool,
    log_file: Path,
    config: dict,
    job_name: str,
    no_clean: bool = False,
) -> bool:
    """Stop a running job."""
    jobs = populate_running_jobs(config["nomad_api_url"], filter_pattern=job_name)
    matching_jobs = []

    for job in jobs:
        if job_name in job.job_id:
            matching_jobs.append(job)

    if len(matching_jobs) == 0:
        log.error(f"No jobs found matching {job_name}")
        return False
    elif len(matching_jobs) > 1:  # pragma: no cover
        print(f"Multiple jobs found matching {job_name}")
        job = select_one(matching_jobs)
    else:
        job = matching_jobs[0]

    if job.stop(no_clean, dry_run):
        if not dry_run:
            alerts.success(f"Stopped job: {job.job_id}")
        return True
    else:
        alerts.error(f"Failed to stop job: {job.job_id}")
        return False
