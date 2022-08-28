"""View logs from container."""

from pathlib import Path

from nd._utils import populate_running_jobs, select_one
from nd._utils.alerts import logger as log


def view_logs(
    verbosity: int,
    dry_run: bool,
    log_to_file: bool,
    log_file: Path,
    config: dict,
    task_name: str,
) -> bool:
    """View logs from a running container.

    Args:
        verbosity (int): Verbosity level.
        dry_run (bool): Whether to run in dry-run mode.
        log_to_file (bool): Whether to log to a file.
        log_file (Path): Path to log file.
        config (dict): Configuration.
        task_name (str): Name of task to view logs for.

    Returns:
        bool: Whether the command succeeded.
    """
    jobs = populate_running_jobs(config["nomad_api_url"])
    matching_tasks = []
    for job in jobs:
        for task in job.tasks:
            if task_name in task.name and task.state == "running":
                matching_tasks.append(task)

    if len(matching_tasks) == 0:
        log.error(f"No tasks found matching {task_name}")
        return False
    elif len(matching_tasks) > 1:
        print(f"Multiple tasks found matching {task_name}")
        task = select_one(matching_tasks)
    else:
        task = matching_tasks[0]

    if task.logs():
        return True
    else:
        return False
