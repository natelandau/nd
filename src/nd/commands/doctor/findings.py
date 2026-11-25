"""The data nd doctor checks read and return: the cluster snapshot and its findings."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from nd.nomad.models.agent import AgentMember
    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.evaluation import EvalListStub
    from nd.nomad.models.job import JobDiff, JobListStub, JobSpec
    from nd.nomad.models.node import NodeListStub
    from nd.nomad.models.volume import HostVolumeListStub


class FindingSeverity(enum.StrEnum):
    """How serious a finding is; critical and warning findings fail the command.

    Members are declared worst first, the order findings print in.
    """

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        """Position in print order, 0 for the worst."""
        return list(FindingSeverity).index(self)


@dataclass(frozen=True)
class Finding:
    """One problem a check found, with where it is and how to fix it when nd can."""

    check: str
    severity: FindingSeverity
    target: str  # `job`, `job/group`, `job/group/task`, `node:NAME`, `server:NAME`, `volume:NAME`
    problem: str
    job_id: str | None = None  # set on job findings, for the web UI link
    job_name: str | None = None  # set on job findings, for the NAME filter and file path
    fix_hint: str | None = None  # the nd command that fixes the finding


# How a running job compares with its local file: the plan's diff, or why there is none.
type JobDrift = JobDiff | str


@dataclass(frozen=True)
class DoctorSnapshot:
    """Everything the checks read, fetched once so each check stays free of I/O."""

    jobs: list[JobListStub]
    job_specs: list[JobSpec]  # dead jobs included, for volume usage
    allocs: list[AllocListStub]
    nodes: list[NodeListStub]
    members: list[AgentMember]
    evals: list[EvalListStub]
    volumes: list[HostVolumeListStub]
    job_file_paths: dict[str, Path]  # job name -> the local file that declares it
    job_directories_configured: bool
    unnamed_job_files: list[Path]  # job files that name their job with a variable
    volume_spec_names: frozenset[str]  # names of local host volume spec files
    # Job name -> plan result for each planned job; None when the `nomad` binary needed
    # to compile the files is missing.
    job_drift: dict[str, JobDrift] | None
    now_ns: int

    @cached_property
    def job_names(self) -> dict[str, str]:
        """Map each job ID to its name, for checks that start from allocations or evaluations."""
        return {job.id: job.name for job in self.jobs}


def job_finding(
    *,
    check: str,
    severity: FindingSeverity,
    job_id: str,
    job_name: str,
    path: tuple[str, ...] = (),
    problem: str,
    fix_hint: str | None = None,
) -> Finding:
    """Build a finding on a job so its target, link, and NAME filter always agree.

    Args:
        check: The check ID.
        severity: How serious the finding is.
        job_id: The job's ID, for the web UI link.
        job_name: The job's name, which starts the target.
        path: Group and task names that narrow the target below the job.
        problem: One line saying what is wrong.
        fix_hint: The nd command that fixes the finding, when one exists.

    Returns:
        Finding: The finding, targeted at `job_name/path...`.
    """
    return Finding(
        check=check,
        severity=severity,
        target="/".join((job_name, *path)),
        problem=problem,
        job_id=job_id,
        job_name=job_name,
        fix_hint=fix_hint,
    )
