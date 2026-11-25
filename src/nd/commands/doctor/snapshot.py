"""Fetch everything nd doctor checks in one pass, so the checks themselves stay pure."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp

from nd.binary import NomadBinary
from nd.binary.env import NomadBinaryError
from nd.commands._common import list_volumes_or_empty
from nd.commands.doctor.findings import DoctorSnapshot
from nd.constants import DOCTOR_COMPILE_CONCURRENCY
from nd.jobfiles import candidates_for, discover_job_files, load_job_directories
from nd.nomad import NomadAuthError, NomadDecodeError, NomadHTTPError, NomadNotFoundError
from nd.volumefiles import discover_volume_files, load_volume_directories

if TYPE_CHECKING:
    from pathlib import Path

    from nd.commands.doctor.findings import JobDrift
    from nd.nomad import NomadClient, NomadConfig
    from nd.nomad.models.job import JobListStub, JobSpec


async def _job_spec_or_none(client: NomadClient, job: JobListStub) -> JobSpec | None:
    """Fetch one job's spec, or None when the job was purged after the listing."""
    try:
        return await client.jobs.get(job.id, namespace=job.namespace)
    except NomadNotFoundError:
        pp.debug(f"Skipping job {job.id}: purged before its spec was fetched")
        return None


def _jobs_to_plan(jobs: list[JobListStub], job_file_paths: dict[str, Path]) -> list[JobListStub]:
    """Pick the jobs whose deployed spec can drift from a file: live, file-backed, not children."""
    return [
        job
        for job in jobs
        if job.status != "dead" and not job.is_child and job.name in job_file_paths
    ]


def _error_summary(text: str) -> str:
    """Pick the line that states the error, so it fits one table cell.

    Nomad leads with a heading such as ``1 error occurred:`` or ``Error parsing job file
    from web.hcl:``, so skip lines ending in a colon when a later line holds the cause.
    """
    lines = [line.strip().removeprefix("* ") for line in text.splitlines() if line.strip()]
    return next((line for line in lines if not line.endswith(":")), lines[0] if lines else "")


async def _plan_against_file(
    *,
    client: NomadClient,
    binary: NomadBinary,
    job: JobListStub,
    path: Path,
    limit: asyncio.Semaphore,
) -> JobDrift:
    """Compile one job file and ask Nomad what deploying it would change.

    A token without plan permission raises `NomadAuthError`, since it fails every job
    the same way and is reported once by the caller.
    """
    try:
        async with limit:
            body = await binary.compile_job(path)
        response = await client.jobs.plan(body, namespace=job.namespace)
    except NomadBinaryError as exc:
        return _error_summary(exc.detail) or str(exc)
    except NomadAuthError:
        raise
    except NomadHTTPError as exc:
        return _error_summary(exc.body) or f"Nomad returned HTTP {exc.status_code}"
    except NomadDecodeError as exc:
        return str(exc)
    return response.diff or "Nomad returned no diff"


@dataclass(frozen=True)
class _DriftResults:
    """Each planned job's result, or why no job could be planned."""

    by_job: dict[JobListStub, JobDrift]
    not_checked: str | None = None


async def _plan_local_jobs(
    *,
    client: NomadClient,
    config: NomadConfig,
    jobs: list[JobListStub],
    job_file_paths: dict[str, Path],
) -> _DriftResults:
    """Plan every job against its local file concurrently.

    The binary is resolved only when a job needs it, so a setup with no local job files
    never hears about a missing binary.
    """
    if not jobs:
        return _DriftResults(by_job={})
    try:
        binary = NomadBinary.create(config)
    except NomadBinaryError as exc:
        pp.debug(f"Skipping drift check: {exc}")
        return _DriftResults(by_job={}, not_checked="nomad binary not found")
    limit = asyncio.Semaphore(DOCTOR_COMPILE_CONCURRENCY)
    # Collect every result so one refused plan does not leave the others unretrieved.
    results = await asyncio.gather(
        *(
            _plan_against_file(
                client=client, binary=binary, job=job, path=job_file_paths[job.name], limit=limit
            )
            for job in jobs
        ),
        return_exceptions=True,
    )
    if any(isinstance(result, NomadAuthError) for result in results):
        return _DriftResults(by_job={}, not_checked="token cannot plan jobs")
    by_job: dict[JobListStub, JobDrift] = {}
    for job, result in zip(jobs, results, strict=True):
        if isinstance(result, BaseException):
            raise result
        by_job[job] = result
    return _DriftResults(by_job=by_job)


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


async def collect_snapshot(client: NomadClient, config: NomadConfig) -> DoctorSnapshot:
    """Fetch the cluster state and local files that every doctor check reads.

    Args:
        client: The API client to read the cluster through.
        config: The connection settings the `nomad` binary uses to compile job files.

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
    jobs_to_plan = _jobs_to_plan(jobs=jobs, job_file_paths=local_files.job_file_paths)
    # A child runs its parent's spec, so fetching it repeats the parent's findings.
    specs, drift = await asyncio.gather(
        asyncio.gather(*(_job_spec_or_none(client, job) for job in jobs if not job.is_child)),
        _plan_local_jobs(
            client=client,
            config=config,
            jobs=jobs_to_plan,
            job_file_paths=local_files.job_file_paths,
        ),
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
        job_drift=drift.by_job,
        drift_not_checked=drift.not_checked,
        now_ns=time.time_ns(),
    )
