"""Display cluster status information."""

from pathlib import Path

import arrow
from rich import box, print
from rich.columns import Columns
from rich.table import Table

from nd._commands.utils import populate_nodes, populate_running_jobs
from nd._commands.utils.alerts import logger as log


def show_cluster_status(
    verbosity: int,
    dry_run: bool,
    log_to_file: bool,
    log_file: Path,
    config: dict,
) -> bool:
    """Display cluster status information."""
    nodes = populate_nodes(config["nomad_api_url"])
    if len(nodes) == 0:
        log.error("No Nomad nodes found")
        return False
    else:
        log.info(f"Found {len(nodes)} nodes in the cluster.")

    jobs = populate_running_jobs(config["nomad_api_url"])
    if len(jobs) == 0:
        log.error("No running jobs found")
        return False
    else:
        log.info(f"Found {len(jobs)} jobs in the cluster.")

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
            f"[link={config['nomad_web_url']}/clients/{node.id_num}]{node.name}[/link]",
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
        i = 0
        for job in sorted(jobs, key=lambda x: x.job_id):
            for task in job.tasks:
                if task.node_id == node.id_num and task.state.lower() == "running":
                    i += 1
                    if task.started == "":
                        runtime = "-"
                    else:
                        runtime = arrow.get(task.started).humanize(only_distance=True)

                    task_table.add_row(
                        str(i),
                        f"[link={config['nomad_web_url']}/allocations/{task.allocation}/{task.name}]{task.name}[/link]",
                        runtime,
                        task.state,
                        str(task.healthy),
                        f"[link={config['nomad_web_url']}/allocations/{task.allocation}/{task.name}/logs]Logs[/link]",
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
        status_tables.append(parent_table)

    columns = Columns(status_tables, equal=False, expand=False)
    print(columns)
    return True
