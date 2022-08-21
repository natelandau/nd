"""Nomad client (node) classes and functions."""

import pyperclip
import rich.repr

from nd._commands.utils import alerts, make_nomad_api_call
from nd._commands.utils.alerts import logger as log


@rich.repr.auto
class Job:
    """Class defining a running Nomad job.

    Methods:
        stop() - Stop a job
    """

    def __init__(
        self,
        api_url: str = "",
        job_id: str = "",
        job_type: str = "",
        status: str = "",
        allocations: list = [],
        tasks: list = [],
    ) -> None:
        self.api_url = api_url
        self.job_id = job_id
        self.job_type = job_type
        self.status = status
        self.allocations, self.tasks = populate_allocations(self.job_id, self.api_url)


@rich.repr.auto
class Allocation:
    """Class for a Nomad allocation.

    Methods:
        None
    """

    def __init__(
        self,
        id_num: str = "",
        node_name: str = "",
        node_id: str = "",
        alloc_type: str = "",
        healthy: bool = False,
    ):
        self.id_num = id_num
        self.id_short = self.id_num.split("-")[0]
        self.node_name = node_name
        self.node_id = node_id
        self.node_id_short = node_id.split("-")[0]
        self.alloc_type = alloc_type
        self.healthy = healthy


@rich.repr.auto
class Task:
    """Class for a Nomad Task.

    Methods:
        execute() - Execute a command in a container
        logs() - View logs from a container
    """

    def __init__(
        self,
        name: str = "",
        allocation: str = "",
        node_name: str = "",
        node_id: str = "",
        started: str = "",
        state: str = "",
        failed: str = "",
        restarts: int = 0,
        healthy: bool = False,
        job_id: str = "",
    ):
        self.name = name
        self.allocation = allocation
        self.allocation_short = self.allocation.split("-")[0]
        self.node_name = node_name
        self.node_id = node_id
        self.node_id_short = self.node_id.split("-")[0]
        self.started = started
        self.state = state
        self.failed = failed
        self.restarts = restarts
        self.healthy = healthy
        self.job_id = job_id

    def execute(self, command: str | None) -> bool:
        """Generate a command to execute in a container and copy it to the users's clipboard.

        Args:
            command: Optional command to execute in the task. Defaults to /bin/sh

        Returns:
            True if the command was copied to the clipboard.
        """
        if command is None:
            cmd = "/bin/sh"
        else:
            cmd = command
        exec_command = f"nomad alloc exec -i -t -task {self.name} {self.allocation_short} {cmd}"
        pyperclip.copy(exec_command)
        alerts.success(f"Command copied to clipboard: {exec_command}")
        return True

    def logs(self) -> bool:
        """Generate a command to execute view logs in a container and copy the command to the users's clipboard.

        Returns:
            True if the command was copied to the clipboard.
        """
        exec_command = f"nomad alloc logs -f -n 50 {self.allocation_short} {self.name}"
        pyperclip.copy(exec_command)
        alerts.success(f"Command copied to clipboard: {exec_command}")
        return True


def populate_running_jobs(nomad_api_url: str, filter_pattern: str | None = None) -> list[Job]:
    """Populate a list of running Job objects fromm the Nomad API.

    Args:
        nomad_api_url (str): The URL of the Nomad HTTP API.
        filter_pattern (str): A regex pattern to filter the jobs by

    Returns:
        List of Job objects
    """
    params = {"filter": f'ID contains "{filter_pattern}"'} if filter_pattern else None
    url = f"{nomad_api_url}/jobs"

    log.trace(f"Populating placed jobs from {url}")
    response = make_nomad_api_call(url, "GET", params)

    if type(response) is list:
        return [Job(nomad_api_url, job["ID"], job["Type"], job["Status"]) for job in response]
    else:
        return []


@log.catch
def populate_allocations(job_id: str, nomad_api_url: str) -> tuple[list[Allocation], list[Task]]:
    """Populate list of running allocations."""
    url = f"{nomad_api_url}/job/{job_id}/allocations"
    response = make_nomad_api_call(url, "GET")
    allocations = []
    tasks = []
    if type(response) is list:
        for alloc in response:

            if (
                alloc["JobType"] == "sysbatch"
                or alloc["JobType"] == "batch"
                or alloc["JobType"] == "system"
            ):
                allocations.append(
                    Allocation(
                        alloc["ID"],
                        alloc["NodeName"],
                        alloc["NodeID"],
                        alloc["JobType"],
                        True,
                    )
                )

                for task in alloc["TaskStates"]:
                    tasks.append(
                        Task(
                            task,
                            alloc["ID"],
                            alloc["NodeName"],
                            alloc["NodeID"],
                            alloc["TaskStates"][task]["StartedAt"],
                            alloc["TaskStates"][task]["State"],
                            alloc["TaskStates"][task]["Failed"],
                            alloc["TaskStates"][task]["Restarts"],
                            True,
                            job_id,
                        )
                    )
            else:
                allocations.append(
                    Allocation(
                        alloc["ID"],
                        alloc["NodeName"],
                        alloc["NodeID"],
                        alloc["JobType"],
                        alloc["DeploymentStatus"]["Healthy"],
                    )
                )

                for task in alloc["TaskStates"]:
                    tasks.append(
                        Task(
                            task,
                            alloc["ID"],
                            alloc["NodeName"],
                            alloc["NodeID"],
                            alloc["TaskStates"][task]["StartedAt"],
                            alloc["TaskStates"][task]["State"],
                            alloc["TaskStates"][task]["Failed"],
                            alloc["TaskStates"][task]["Restarts"],
                            alloc["DeploymentStatus"]["Healthy"],
                            job_id,
                        )
                    )

        return allocations, tasks
    else:
        return [], []
