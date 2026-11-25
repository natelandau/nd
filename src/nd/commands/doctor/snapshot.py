"""Fetch everything nd doctor checks in one pass, so the checks themselves stay pure."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp

from nd.commands._common import list_volumes_or_empty
from nd.commands.doctor.findings import DoctorSnapshot
from nd.jobfiles import candidates_for, discover_job_files, load_job_directories
from nd.nomad import NomadNotFoundError
from nd.volumefiles import discover_volume_files, load_volume_directories

if TYPE_CHECKING:
    from pathlib import Path

    from nd.nomad import NomadClient
    from nd.nomad.models.job import JobListStub, JobSpec


async def _job_spec_or_none(client: NomadClient, job: JobListStub) -> JobSpec | None:
    """Fetch one job's spec, or None when the job was purged after the listing."""
    try:
        return await client.jobs.get(job.id, namespace=job.namespace)
    except NomadNotFoundError:
        pp.debug(f"Skipping job {job.id}: purged before its spec was fetched")
        return None


@dataclass(frozen=True)
class _LocalFiles:
    """The local job and volume files the checks compare the cluster against."""

    job_file_paths: dict[str, Path]
    job_directories_configured: bool
    unnamed_job_files: list[Path]
    volume_spec_names: frozenset[str]


def _discover_local_files() -> _LocalFiles:
    """Read the configured job and volume directories; the first file to declare a job wins."""
    job_directories = load_job_directories()
    job_files = discover_job_files(job_directories)
    candidates = candidates_for(job_files)
    return _LocalFiles(
        job_file_paths={c.name: c.file.path for c in reversed(candidates)},
        job_directories_configured=bool(job_directories),
        unnamed_job_files=[jf.path for jf in job_files if not jf.job_names],
        volume_spec_names=frozenset(
            spec.name for spec in discover_volume_files(load_volume_directories())
        ),
    )


async def collect_snapshot(client: NomadClient) -> DoctorSnapshot:
    """Fetch the cluster state and local files that every doctor check reads.

    Returns:
        DoctorSnapshot: The listings, every job's full spec, and the local file index.
    """
    # File parsing is blocking, so it runs in a thread while the listings load. One
    # outer gather retrieves the thread's result or error even when a listing fails.
    listings, local_files = await asyncio.gather(
        asyncio.gather(
            client.jobs.list(),
            client.allocations.list(),
            client.nodes.list(),
            client.agent.members(),
            client.evaluations.list(),
            list_volumes_or_empty(client),
        ),
        asyncio.to_thread(_discover_local_files),
    )
    jobs, allocs, nodes, members, evals, volumes = listings
    # A child runs its parent's spec, so fetching it repeats the parent's findings.
    specs = await asyncio.gather(
        *(_job_spec_or_none(client, job) for job in jobs if not job.is_child)
    )

    return DoctorSnapshot(
        jobs=jobs,
        job_specs=[spec for spec in specs if spec is not None],
        allocs=allocs,
        nodes=nodes,
        members=members,
        evals=evals,
        volumes=volumes,
        job_file_paths=local_files.job_file_paths,
        job_directories_configured=local_files.job_directories_configured,
        unnamed_job_files=local_files.unnamed_job_files,
        volume_spec_names=local_files.volume_spec_names,
        now_ns=time.time_ns(),
    )
