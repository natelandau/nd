"""Helper functions for the nd package."""

from pathlib import Path

import arrow
from rich import box
from rich.columns import Columns
from rich.table import Table

from nd.config.config import Config
from nd.models.job import Job
from nd.models.job_files import JobFile
from nd.models.node import Node
from nd.models.nomad_api import NomadAPI
from nd.utils.alerts import logger as log
from nd.utils.console import console


def find_job_files(
    config: Config,
    api: NomadAPI = None,
    search_string: str | None = None,
) -> list[JobFile]:
    """Find all valid Nomad job files in a list of directories.

    Args:
        api (NomadAPI, optional): NomadAPI object. Defaults to None.
        config (Config): Config object.
        search_string (str, optional): String to search for in job file names. Defaults to None.

    Returns:
        list[JobFile]: List of JobFile objects.
    """
    job_files = []

    with console.status(
        "Processing Files...  [dim](Can take a while for large directory trees)[/]",
        spinner="bouncingBall",
    ):
        for directory in config.job_file_locations:
            _dir = Path(directory).expanduser()

            if not _dir.is_dir():
                continue

            files = [
                f
                for f in _dir.glob("**/*")
                if f.is_file()
                and (f.suffix in {".nomad", ".hcl"})
                and not any(s.lower() in f.name.lower() for s in config.file_ignore_strings)
            ]

            job_files.extend(
                [
                    JobFile(
                        file,
                        nomad_api=api,
                        dry_run=config.dry_run,
                        nomad_address=config.nomad_address,
                    )
                    for file in files
                ]
            )

            job_files = [
                j
                for j in job_files
                if j.valid and (search_string is None or search_string.lower() in j.name.lower())
            ]

    log.debug(f"Found valid {len(list(set(job_files)))} job files.")
    return sorted(set(job_files), key=lambda x: x.name)


def find_nodes(api: NomadAPI, filter_pattern: str | None = None) -> list[Node]:
    """Find all nodes in a Nomad cluster.

    Args:
        api (NomadAPI): NomadAPI object.
        filter_pattern (str, optional): String to search for in node names. Defaults to None.

    Returns:
        list[Node]: List of Node objects.
    """
    params = {"filter": f'Name contains "{filter_pattern}"'} if filter_pattern else None

    with console.status(
        "Processing Nodes...  [dim](Can take a while for large clusters)[/]",
        spinner="bouncingBall",
    ):
        nodes = [
            Node(
                address=node["Address"],
                datacenter=node["Datacenter"],
                eligible=node["SchedulingEligibility"],
                id_num=node["ID"],
                name=node["Name"],
                node_class=node["NodeClass"],
                status=node["Status"],
                version=node["Version"],
            )
            for node in api.get_nodes(data=params)
        ]

    log.debug(f"Found {len(nodes)} nodes.")
    return sorted(nodes, key=lambda x: x.name)


def find_running_jobs(
    api: NomadAPI,
    nomad_address: str,
    filter_pattern: str | None = None,
    dry_run: bool = False,
) -> list[Job]:
    """Find all jobs in a Nomad cluster.

    Args:
        api (NomadAPI): NomadAPI object.
        filter_pattern (str, optional): String to search for in job names. Defaults to None.
        dry_run (bool, optional): Sets the dry_run flag for the Nomad API. Defaults to False.
        nomad_address (str, optional): Nomad address. Defaults to None.

    Returns:
        list[Job]: List of Job objects.
    """
    params = {"filter": f'ID contains "{filter_pattern}"'} if filter_pattern else None

    with console.status(
        "Processing Jobs...  [dim](Can take a while for large clusters)[/]",
        spinner="bouncingBall",
    ):
        jobs = [
            Job(
                create_index=job["CreateIndex"],
                dry_run=dry_run,
                job_id=job["ID"],
                job_name=job["Name"],
                job_type=job["Type"],
                modify_index=job["ModifyIndex"],
                nomad_api=api,
                nomad_address=nomad_address,
                parameterized=job["ParameterizedJob"],
                periodic=job["Periodic"],
                status=job["Status"],
            )
            for job in api.get_jobs(data=params)
        ]

    log.debug(f"Found {len(jobs)} running jobs.")
    return sorted(jobs, key=lambda x: x.name)


def print_table(
    columns: list[str],
    rows: list[list[str]],
    highlight: bool = False,
    title: str | None = None,
    footer: str | None = None,
) -> None:  # pragma: no cover
    """Print a table to the console.

    To add style to a row, add a string to the last column of the row with the format "style:<style>".

    Args:
        title (str): Title of the table.
        columns (list[str]): List of column headers.
        highlight (bool): Whether to use rich highlighting on the row. Default is False
        rows (list[list[Any]]): List of lists containing the data to display.
        footer (str): Footer text to display.
    """
    table = Table(
        box=box.DOUBLE_EDGE,
        caption=footer if footer else None,
        header_style="bold",
        highlight=highlight,
        show_edge=True,
        show_header=True,
        show_lines=False,
        title=title if title else None,
    )
    for column in columns:
        table.add_column(column, justify="left", no_wrap=False)

    for row in rows:
        if "style:none" in row[-1].lower():
            table.add_row(*row[:-1])
        elif "style:" in row[-1]:
            table.add_row(*row[:-1], style=row[-1].split(":")[1])
        else:
            table.add_row(*row)

    console.print(table)


def print_status_table(
    nodes: list[Node], jobs: list[Job], nomad_address: str
) -> None:  # pragma: no cover
    """Print the status of all jobs and nodes."""
    status_tables = []

    for node in sorted(nodes, key=lambda x: x.name):
        parent_table = Table(
            title=node.name,
            caption=" ",
            show_header=False,
            box=box.DOUBLE_EDGE,
            padding=0,
            min_width=60,
            style="reverse",
        )

        node_table = Table(
            style="cyan reverse",
            box=None,
            show_header=False,
            show_footer=False,
        )
        node_table.add_column("key", justify="right", style="bold")
        node_table.add_column("value")
        node_table.add_row(
            "Node Name:",
            f"[link={nomad_address}/ui/clients/{node.id_num}]{node.name}[/link]",
        )
        node_table.add_row("Node ID:", node.id_short)
        node_table.add_row("IP Address:", node.address)
        node_table.add_row("Status:", node.status)
        node_table.add_row("Elibility:", node.eligible)

        parent_table.add_row(node_table, style="reverse")

        task_table = Table(
            style="reverse",
            box=box.SIMPLE,
            show_footer=False,
            pad_edge=False,
            min_width=55,
        )
        task_table.add_column("#", header_style="bold")
        task_table.add_column("Task", header_style="bold")
        task_table.add_column("Runtime", header_style="bold")
        task_table.add_column("State", header_style="bold")
        task_table.add_column("Healthy", header_style="bold")
        task_table.add_column("Logs", header_style="bold")

        ###################################
        i = 0
        running_tasks = [
            task
            for job in jobs
            for allocation in job.allocations
            for task in allocation.tasks
            if task.node_id == node.id_num and task.state.lower() == "running"
        ]

        for task in running_tasks:
            if task.node_id == node.id_num and task.state.lower() == "running":
                i += 1
                runtime = (
                    arrow.get(task.started).humanize(only_distance=True) if task.started else "-"
                )

                task_table.add_row(
                    str(i),
                    f"[link={nomad_address}/ui/allocations/{task.alloc_id}/{task.name}]{task.name}[/link]",
                    runtime,
                    task.state,
                    str(task.healthy),
                    f"[link={nomad_address}/ui/allocations/{task.alloc_id}/{task.name}/logs]Logs[/link]",
                )
        if i == 0:
            task_table.add_row(
                "",
                "No running jobs",
                "",
                "",
                "",
                "",
            )

        parent_table.add_row(task_table, style=" reverse")

        ###############################
        status_tables.append(parent_table)

    console.print(Columns(status_tables, equal=False, expand=False, align="center"))
