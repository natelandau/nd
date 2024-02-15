"""Representation of a job running in Nomad."""
import time

import rich.repr
import sh
import typer
from loguru import logger
from rich.progress import track

from nd.models.nomad_api import NomadAPI
from nd.utils.console import console


@rich.repr.auto
class Task:
    """Representation of a task running in Nomad.

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

    def __init__(  # noqa: PLR0917
        self,
        alloc_id: str,
        failed: bool,
        finished: str,
        healthy: bool,
        job_id: str,
        name: str,
        node_id: str,
        node_name: str,
        nomad_address: str,
        restarts: int,
        started: str,
        state: str,
    ):  # pragma: no cover
        self.alloc_id = alloc_id
        self.alloc_short = alloc_id.split("-")[0]
        self.failed = failed
        self.finished = finished
        self.healthy = healthy
        self.job_id = job_id
        self.name = name
        self.node_id = node_id
        self.node_name = node_name
        self.nomad_address = nomad_address
        self.restarts = restarts
        self.started = started
        self.state = state

    def __rich_repr__(self) -> rich.repr.RichReprResult:  # pragma: no cover  # noqa: PLW3201
        """Rich representation of the Job object."""
        yield "alloc_id", self.alloc_id
        yield "alloc_short", self.alloc_short
        yield "healthy", self.healthy
        yield "name", self.name
        yield "node_id", self.node_id
        yield "node_name", self.node_name
        yield "nomad_address", self.nomad_address
        yield "state", self.state
        yield "started", self.started
        yield "failed", self.failed
        yield "restarts", self.restarts
        yield "finished", self.finished

    def execute(self, command: str) -> None:  # pragma: no cover
        """Generate a command to execute in a container and copy it to the users's clipboard.

        Args:
            command (str | None): The command to execute. (Defaults to `/bin/sh`)

        """
        try:
            sh.nomad(
                "alloc",
                "exec",
                f"-address={self.nomad_address}",
                "-no-color",
                "-i",
                "-t",
                "-task",
                self.name,
                "-job",
                self.job_id,
                command,
                _fg=True,
            )
        except sh.ErrorReturnCode as e:
            raise typer.Exit() from e

    def logs(self) -> None:  # pragma: no cover
        """Generate a command to execute view logs in a container and copy the command to the users's clipboard."""
        try:
            sh.nomad(
                "alloc",
                "logs",
                f"-address={self.nomad_address}",
                "-no-color",
                "-f",
                "-tail",
                "-n",
                "50",
                self.alloc_short,
                self.name,
                _fg=True,
            )
        except sh.ErrorReturnCode as e:
            logger.error(f"Failed to get logs for {self.name} in {self.alloc_short}")
            raise typer.Exit() from e


@rich.repr.auto
class Allocation:
    """Representation of a Nomad allocation.

    Attributes:
        id_num (str): The ID of the allocation.
        id_short (str): The short ID of the allocation.
        node_name (str): The name of the node.
        node_id (str): The ID of the node.
        node_id_short (str): The short ID of the node.
        alloc_type (str): The type of the allocation.
        healthy (bool): Whether or not the allocation is healthy.
    """

    def __init__(  # noqa: PLR0917
        self,
        alloc_name: str,
        id_num: str,
        job_id: str,
        job_type: str,
        node_id: str,
        node_name: str,
        nomad_address: str,
        task_group: str,
        healthy: bool,
        tasks: list[Task],
    ):  # pragma: no cover
        self.alloc_name = alloc_name
        self.id_num = id_num
        self.job_id = job_id
        self.job_type = job_type
        self.healthy = healthy
        self.node_id = node_id
        self.node_name = node_name
        self.nomad_address = nomad_address
        self.task_group = task_group
        self.id_short = self.id_num.split("-")[0]
        self.node_id_short = node_id.split("-")[0]
        self.tasks = tasks

    def __rich_repr__(self) -> rich.repr.RichReprResult:  # pragma: no cover  # noqa: PLW3201
        """Rich representation of the Job object."""
        yield "alloc_name", self.alloc_name
        yield "healthy", self.healthy
        yield "id_num", self.id_num
        yield "id_short", self.id_short
        yield "job_id", self.job_id
        yield "job_type", self.job_type
        yield "node_id_short", self.node_id_short
        yield "node_id", self.node_id
        yield "node_name", self.node_name
        yield "nomad_address", self.nomad_address
        yield "task_group", self.task_group
        yield "tasks", self.tasks


@rich.repr.auto
class Job:
    """Representation of a job running in Nomad."""

    def __init__(  # noqa: PLR0917
        self,
        create_index: int,
        dry_run: bool,
        job_id: str,
        job_name: str,
        job_type: str,
        modify_index: int,
        nomad_api: NomadAPI,
        nomad_address: str,
        parameterized: bool,
        periodic: bool,
        status: str,
    ):  # pragma: no cover
        self.api = nomad_api
        self.create_index = create_index
        self.dry_run = dry_run
        self.id = job_id
        self.modify_index = modify_index
        self.name = job_name
        self.nomad_address = nomad_address
        self.parameterized = parameterized
        self.periodic = periodic
        self.status = status
        self.type = job_type
        self.allocations = self._get_allocations()
        self.creates_backup = any(
            task for alloc in self.allocations for task in alloc.tasks if "filesystem" in task.name
        )

    def __hash__(self) -> int:
        """Hash the Job object."""
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        """Compare two Job objects."""
        if not isinstance(other, Job):
            return NotImplemented

        return self.id == other.id

    def __rich_repr__(self) -> rich.repr.RichReprResult:  # pragma: no cover  # noqa: PLW3201
        """Rich representation of the Job object."""
        yield "allocations", self.allocations
        yield "create_index", self.create_index
        yield "creates_backup", self.creates_backup
        yield "dry_run", self.dry_run
        yield "id", self.id
        yield "modify_index", self.modify_index
        yield "name", self.name
        yield "nomad_address", self.nomad_address
        yield "parameterized", self.parameterized
        yield "periodic", self.periodic
        yield "status", self.status
        yield "type", self.type

    def _get_allocations(self) -> list[Allocation]:
        """Get running allocations for the job.

        Returns:
            list[Allocation]: A list of allocations for the job.
        """
        result = self.api.get_allocations(job_id=self.id)
        try:
            return [
                Allocation(
                    alloc_name=alloc["Name"],
                    healthy=alloc["DeploymentStatus"]["Healthy"]
                    if self.type == "service"
                    else True,
                    id_num=alloc["ID"],
                    job_id=self.id,
                    job_type=self.type,
                    node_id=alloc["NodeID"],
                    node_name=alloc["NodeName"],
                    nomad_address=self.nomad_address,
                    task_group=alloc["TaskGroup"],
                    tasks=[
                        Task(
                            name=t,
                            alloc_id=alloc["ID"],
                            failed=alloc["TaskStates"][t]["Failed"],
                            finished=alloc["TaskStates"][t]["FinishedAt"],
                            healthy=alloc["DeploymentStatus"]["Healthy"],
                            job_id=self.id,
                            node_id=alloc["NodeID"],
                            node_name=alloc["NodeName"],
                            nomad_address=self.nomad_address,
                            restarts=alloc["TaskStates"][t]["Restarts"],
                            started=alloc["TaskStates"][t]["StartedAt"],
                            state=alloc["TaskStates"][t]["State"],
                        )
                        for t in alloc["TaskStates"]
                    ],
                )
                for alloc in result
            ]
        except TypeError as e:
            logger.error(f"Error getting allocations for job {self.id}: {e}")
            console.print(result)
            return []

    def stop(self, no_clean: bool = False) -> bool:  # pragma: no cover
        """Stop the job.

        Args:
            no_clean (bool, optional): Whether or not to garbage collect the job. Defaults to False.

        Returns:
            bool: Whether or not the job was stopped.
        """
        params = None if no_clean else {"purge": "true"}
        if self.api.stop_job(job_id=self.id, params=params):
            if not self.dry_run:
                for _idx, _value in enumerate(
                    track(
                        range(200),
                        description=f"[{self.name}] Stopping...",
                        transient=True,
                    )
                ):
                    time.sleep(0.01)

                if self.creates_backup:  # pragma: no cover
                    for _idx, _value in enumerate(
                        track(
                            range(4000),
                            description=f"[{self.name}] Creating backup...",
                            transient=True,
                        )
                    ):
                        time.sleep(0.01)

            logger.success(f"Stopped job {self.id}")
            return True

        logger.error(f"Failed to stop job {self.id}")
        return False
