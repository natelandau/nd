"""Checks of allocations, evaluations, machines, local job files, and host volumes."""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from nd.commands.doctor.findings import DoctorSnapshot, Finding, FindingSeverity, job_finding
from nd.ui.text import plural

if TYPE_CHECKING:
    from collections.abc import Iterable

    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.job import JobDiff

# Client statuses of an allocation whose node stopped reporting.
_LOST_ALLOC_STATUSES = frozenset({"lost", "unknown"})
_HOST_VOLUME = "host"
# Server statuses that need no action: a server removed on purpose stays listed as
# `left` until serf reaps it.
_EXPECTED_SERVER_STATUSES = frozenset({"alive", "left"})
# The `[N]` allocation index Nomad appends to the source of a `per_alloc` volume request.
_PER_ALLOC_INDEX_RE = re.compile(r"\[\d+\]$")


def _group_findings(
    snapshot: DoctorSnapshot,
    allocs: Iterable[AllocListStub],
    *,
    check: str,
    severity: FindingSeverity,
    noun: str,
) -> list[Finding]:
    """Count allocations per job and group, and build one finding for each pair."""
    counts = Counter((alloc.job_id, alloc.task_group) for alloc in allocs)
    return [
        job_finding(
            check=check,
            severity=severity,
            job_id=job_id,
            job_name=snapshot.job_names.get(job_id, job_id),
            path=(group,),
            problem=plural(count, noun),
        )
        for (job_id, group), count in sorted(counts.items())
    ]


def check_failed_alloc(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag failed allocations that Nomad wants running and has not replaced.

    Returns:
        list[Finding]: One critical finding per job and group.
    """
    return _group_findings(
        snapshot,
        (a for a in snapshot.allocs if a.is_current and a.client_status == "failed"),
        check="failed-alloc",
        severity=FindingSeverity.CRITICAL,
        noun="failed allocation",
    )


def check_lost_alloc(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag allocations whose node stopped reporting and that Nomad has not replaced.

    Returns:
        list[Finding]: One warning per job and group.
    """
    return _group_findings(
        snapshot,
        (a for a in snapshot.allocs if a.is_current and a.client_status in _LOST_ALLOC_STATUSES),
        check="lost-alloc",
        severity=FindingSeverity.WARNING,
        noun="lost allocation",
    )


def check_blocked_eval(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag evaluations the scheduler is stuck on.

    Returns:
        list[Finding]: One warning per job with a stuck evaluation.
    """
    stuck = {e.job_id: e.status for e in snapshot.evals if e.is_problem}
    return [
        job_finding(
            check="blocked-eval",
            severity=FindingSeverity.WARNING,
            job_id=job_id,
            job_name=snapshot.job_names.get(job_id, job_id),
            problem=status,
        )
        for job_id, status in sorted(stuck.items())
    ]


def check_node_down(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag client nodes that are not ready and servers that are neither alive nor left.

    Returns:
        list[Finding]: One critical finding per unhealthy machine.
    """
    nodes = [
        Finding(
            check="node-down",
            severity=FindingSeverity.CRITICAL,
            target=f"node:{node.name}",
            problem=node.status,
        )
        for node in sorted(snapshot.nodes, key=lambda n: n.name)
        if node.status != "ready"
    ]
    servers = [
        Finding(
            check="node-down",
            severity=FindingSeverity.CRITICAL,
            target=f"server:{member.short_name}",
            problem=f"server {member.status}",
        )
        for member in sorted(snapshot.members, key=lambda m: m.name)
        if member.status not in _EXPECTED_SERVER_STATUSES
    ]
    return nodes + servers


def check_no_local_file(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag jobs in the cluster that no local job file declares.

    Periodic and parameterized children are skipped, since only their parent has a file.
    Returns nothing when no job directories are configured, since every job would match.
    A file that names its job with a variable could declare any job, so while one exists
    no finding offers to stop its job.

    Returns:
        list[Finding]: One info finding per job that is not dead and has no file.
    """
    if not snapshot.job_directories_configured:
        return []
    names_unknown = bool(snapshot.unnamed_job_files)
    problem = "job name may be templated" if names_unknown else ""
    return [
        job_finding(
            check="no-local-file",
            severity=FindingSeverity.INFO,
            job_id=job.id,
            job_name=job.name,
            problem=problem,
            fix_hint=f"nd stop {job.name}" if job.is_running and not names_unknown else None,
        )
        for job in sorted(snapshot.jobs, key=lambda j: j.name)
        if job.status != "dead" and not job.is_child and job.name not in snapshot.job_file_paths
    ]


def _describe_diff(diff: JobDiff) -> str:
    """Say what a plan would change in one short cell: a group, a group's task, or a count."""
    groups = [group for group in diff.task_groups if group.type != "None"]
    if not groups:
        return "job settings"
    if len(groups) > 1:
        return f"{len(groups)} groups"
    group = groups[0]
    tasks = [task.name for task in group.tasks if task.type != "None"]
    # A task named like its group adds nothing to the group's name.
    if len(tasks) == 1 and tasks[0] != group.name:
        return f"{group.name}/{tasks[0]}"
    return group.name


def check_job_drift(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag running jobs whose deployed spec differs from their local job file.

    Returns:
        list[Finding]: One warning per edited job or job whose plan failed, by job name,
            or one info finding saying why no job could be compared.
    """
    if snapshot.drift_not_checked is not None:
        return [
            Finding(
                check="drift-not-checked",
                severity=FindingSeverity.INFO,
                target="job-drift",
                problem=snapshot.drift_not_checked,
            )
        ]
    findings: list[Finding] = []
    for job, drift in sorted(snapshot.job_drift.items(), key=lambda item: item[0].name):
        if isinstance(drift, str):
            problem, fix_hint = f"plan failed: {drift}", None
        elif drift.is_changed:
            problem, fix_hint = _describe_diff(drift), f"nd plan {job.name}"
        else:
            continue
        findings.append(
            job_finding(
                check="job-drift",
                severity=FindingSeverity.WARNING,
                job_id=job.id,
                job_name=job.name,
                problem=problem,
                fix_hint=fix_hint,
            )
        )
    return findings


def check_unused_volume(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag dynamic host volumes that no job in the cluster requests, stopped jobs included.

    A `per_alloc` request claims every volume named after its source plus an allocation
    index, such as `data[0]`.

    Returns:
        list[Finding]: One info finding per unused volume name.
    """
    host_requests = [
        request
        for spec in snapshot.job_specs
        for group in spec.task_groups
        for request in group.volumes.values()
        if request.type == _HOST_VOLUME and request.source
    ]
    exact_sources = {request.source for request in host_requests if not request.per_alloc}
    per_alloc_sources = {request.source for request in host_requests if request.per_alloc}

    def is_requested(name: str) -> bool:
        source, index_count = _PER_ALLOC_INDEX_RE.subn("", name)
        return name in exact_sources or (index_count == 1 and source in per_alloc_sources)

    return [
        Finding(
            check="unused-volume",
            severity=FindingSeverity.INFO,
            target=f"volume:{name}",
            problem="",
            fix_hint=f"nd volume delete {name}" if name in snapshot.volume_spec_names else None,
        )
        for name in sorted({volume.name for volume in snapshot.volumes})
        if not is_requested(name)
    ]
