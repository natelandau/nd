"""The ``nd list`` command: list known job files against live cluster state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer
from nclutils import pp

from nd.commands._common import VerboseOption, configure_verbosity
from nd.jobfiles import discover_job_files, load_job_directories
from nd.nomad import NomadClient, NomadConfig
from nd.ui.links import job_url, link
from nd.ui.panels import status_table, titled_panel
from nd.ui.styles import status_cell

if TYPE_CHECKING:
    from nd.jobfiles import JobFile
    from nd.nomad.models.job import JobListStub

# Cluster-status label for a job file whose name is not present in Nomad at all.
_NOT_DEPLOYED = "not deployed"


@dataclass(frozen=True)
class ListRow:
    """One rendered row: a job file's name, path, and cluster status."""

    job_name: str
    path: str
    cluster_status: str
    # Nomad job ID for the web UI link, or None when the job is not deployed.
    link_id: str | None


def build_rows(files: list[JobFile], jobs: list[JobListStub]) -> list[ListRow]:
    """Join discovered job files to cluster jobs by name, classifying each.

    A file with no resolved job name still appears (named ``?``) so unresolved
    interpolated names are visible rather than silently dropped. A deployed job
    carries its Nomad ID so its name can be linked to the web UI.

    Args:
        files: Discovered job files to classify.
        jobs: Live cluster jobs to join against.

    Returns:
        Sorted list of rows, one per job name per file.
    """
    jobs_by_name = {job.name: job for job in jobs}
    rows: list[ListRow] = []
    for jf in files:
        names = jf.job_names or ["?"]
        for name in names:
            job = jobs_by_name.get(name)
            status = job.status if job else _NOT_DEPLOYED
            link_id = job.id if job else None
            rows.append(
                ListRow(job_name=name, path=str(jf.path), cluster_status=status, link_id=link_id)
            )
    return sorted(rows, key=lambda r: r.job_name)


def _render(rows: list[ListRow], ui_base: str) -> None:
    """Print the job-file table inside a titled panel, linking deployed jobs to the web UI."""
    if not rows:
        pp.info("No job files found; set [jobs] directories in your nd config.")
        return
    table = status_table("JOB", "STATUS", "FILE")
    for row in rows:
        name = link(job_url(ui_base, row.link_id), row.job_name) if row.link_id else row.job_name
        # "not deployed" is not a Nomad status, so style it muted rather than via status_cell.
        cell = (
            status_cell(row.cluster_status)
            if row.cluster_status != _NOT_DEPLOYED
            else "[dim]• not deployed[/]"
        )
        table.add_row(name, cell, row.path)
    pp.console().print(titled_panel(table, "Job files"))


app = typer.Typer()


@app.callback(invoke_without_command=True)
def list_(ctx: typer.Context, verbose: VerboseOption = 0) -> None:
    """List known job files and whether each is running, dead, or not deployed."""
    configure_verbosity(ctx, verbose)
    asyncio.run(_run())


async def _run() -> None:
    """Discover job files, fetch cluster jobs, and render the joined table."""
    directories = load_job_directories()
    files = discover_job_files(directories)
    pp.debug(f"Discovered {len(files)} job file(s) in {len(directories)} dir(s)")
    config = NomadConfig.resolve()
    async with NomadClient.from_config(config) as client:
        jobs = await client.jobs.list()
    _render(build_rows(files, jobs), config.ui_base)
