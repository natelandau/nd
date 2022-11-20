"""Nomad client (node) classes and functions."""

import time

import rich.repr
from plumbum import FG, CommandNotFound, ProcessExecutionError, local
from rich.progress import track

from nd._utils import make_nomad_api_call
from nd._utils.alerts import logger as log


@rich.repr.auto
class Job:
    """Class defining a running Nomad job.

    Attributes:
        api_url (str): The URL of the Nomad HTTP API.
        job_id (str): The ID of the job.
        job_type (str): The type of the job.
        status (str): The status of the job.
        allocations (list[Allocation]): The allocations of the job.
        tasks (list[Task]): The tasks of the job.
        create_backup (bool): Whether or not the job creates a backup when stopped.
    """

    def __init__(
        self,
        api_url: str = "",
        job_id: str = "",
        job_type: str = "",
        status: str = "",
        allocations: list = [],
        tasks: list = [],
        create_backup: bool = False,
    ) -> None:
        self.api_url = api_url
        self.job_id = job_id
        self.job_type = job_type
        self.status = status
        self.create_backup = create_backup
        self.allocations, self.tasks = populate_allocations(self.job_id, self.api_url)

        for task in self.tasks:
            if "filesystem" in task.name:
                self.create_backup = True
                break

    def stop(self, no_clean: bool = False, dry_run: bool = False) -> bool:
        """Stop a job.

        Args:
            no_clean (bool): Whether or not to clean up the job after stopping.
            dry_run (bool): Whether or not to actually stop the job.

        Returns:
            bool: Whether or not the job was stopped.
        """
        log.info(f"Stopping job {self.job_id}")

        api_url = f"{self.api_url}/job/{self.job_id}"
        if no_clean:
            params = None
        else:
            params = {"purge": "true"}

        if make_nomad_api_call(api_url, "DELETE", data=params, dry_run=dry_run):
            if not dry_run:
                for _idx, _value in enumerate(
                    track(
                        range(200),
                        description=f"[{self.job_id}] Stopping {self.job_id}...",
                        transient=True,
                    )
                ):
                    time.sleep(0.01)

                if self.create_backup:  # pragma: no cover
                    for _idx, _value in enumerate(
                        track(
                            range(4000),
                            description=f"Creating {self.job_id} backup...",
                            transient=True,
                        )
                    ):
                        time.sleep(0.01)

            return True

        return False


@rich.repr.auto
class Allocation:
    """Class for a Nomad allocation.

    Attributes:
        id_num (str): The ID of the allocation.
        id_short (str): The short ID of the allocation.
        node_name (str): The name of the node.
        node_id (str): The ID of the node.
        node_id_short (str): The short ID of the node.
        alloc_type (str): The type of the allocation.
        healthy (bool): Whether or not the allocation is healthy.
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

    Attributes:
        name (str): The name of the task.
        allocation (str): The allocation of the task.
        node_name (str): The name of the node.
        node_id (str): The ID of the node.
        started (str): The time the task started.
        state (str): The state of the task.
        failed (str): The time the task failed.
        restarts (int): The number of restarts the task has had.
        healthy (bool): Whether or not the task is healthy.
        job_id (str): The ID of the job.
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
            command (str | None): The command to execute. (Defaults to `/bin/sh`)

        Returns:
            bool: Whether or not the command was executed.
        """
        if command is None:
            cmd = "/bin/sh"
        else:
            cmd = command

        try:
            nomad = local["nomad"]
            nomad["alloc", "exec", "-i", "-t", "-task", self.name, self.allocation_short, cmd] & FG
        except CommandNotFound:
            log.error("Nomad binary is not installed")  # noqa: TC400
            return False
        except ProcessExecutionError as e:
            log.error(e)  # noqa: TC400
            return False

        return True

    def logs(self) -> bool:
        """Generate a command to execute view logs in a container and copy the command to the users's clipboard.

        Returns:
            bool: Whether or not the command was executed to display logs.
        """
        try:
            nomad = local["nomad"]
            nomad["alloc", "logs", "-f", "-n", "50", self.allocation_short, self.name] & FG
        except CommandNotFound:
            log.error("Nomad binary is not installed")  # noqa: TC400
            return False
        except ProcessExecutionError as e:
            log.error(e)  # noqa: TC400
            return False

        return True


@log.catch
def populate_running_jobs(nomad_api_url: str, filter_pattern: str | None = None) -> list[Job]:
    """Populate a list of running Job objects fromm the Nomad API.

    Args:
        nomad_api_url (str): The URL of the Nomad API.
        filter_pattern (str | None): The pattern to filter jobs by. (Defaults to None)

    Returns:
        list[Job]: A list of Job objects.
    """
    params = {"filter": f'ID contains "{filter_pattern}"'} if filter_pattern else None
    url = f"{nomad_api_url}/jobs"

    log.trace(f"Populating placed jobs from {url}")
    response = make_nomad_api_call(url, "GET", params)

    if type(response) is list:
        return [Job(nomad_api_url, job["ID"], job["Type"], job["Status"]) for job in response]

    return []


@log.catch
def populate_allocations(job_id: str, nomad_api_url: str) -> tuple[list[Allocation], list[Task]]:
    """Populate list of running allocations.

    Args:
        job_id (str): The ID of the job.
        nomad_api_url (str): The URL of the Nomad API.

    Returns:
        tuple[list[Allocation], list[Task]]: A tuple of lists of Allocation and Task objects.
    """
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

    return [], []
