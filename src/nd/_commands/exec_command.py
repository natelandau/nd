"""Execute a command in a container."""

from pathlib import Path

from rich import print

from nd._commands.utils import populate_running_jobs, select_one
from nd._commands.utils.alerts import logger as log


@log.catch
def exec_in_container(
    verbosity: int,
    dry_run: bool,
    log_to_file: bool,
    log_file: Path,
    config: dict,
    task_name: str,
    exec_command: str | None,
) -> bool:
    """Execute a command in a container."""
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
        task.execute(exec_command)
        return True
    else:
        task = matching_tasks[0]
        task.execute(exec_command)
        return True
