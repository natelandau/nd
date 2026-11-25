"""Checks of each job's spec and its tasks' run state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nd.commands.doctor.findings import DoctorSnapshot, Finding, FindingSeverity, job_finding
from nd.constants import (
    DOCTOR_RESTART_THRESHOLD,
    DOCTOR_RESTART_WINDOW_SECONDS,
    NOMAD_DEFAULT_CPU_MHZ,
    NOMAD_DEFAULT_MEMORY_MB,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from nd.nomad.models.job import JobSpec, TaskGroupSpec, TaskSpec


def _live_groups(snapshot: DoctorSnapshot) -> Iterator[tuple[JobSpec, TaskGroupSpec]]:
    """Yield every task group of every job that is not dead, with its job."""
    for spec in snapshot.job_specs:
        if not spec.is_dead:
            for group in spec.task_groups:
                yield spec, group


def _live_tasks(snapshot: DoctorSnapshot) -> Iterator[tuple[JobSpec, TaskGroupSpec, TaskSpec]]:
    """Yield every task of every job that is not dead, with its job and group."""
    for spec, group in _live_groups(snapshot):
        for task in group.tasks:
            yield spec, group, task


def _is_unpinned(image: str) -> bool:
    """Return True when an image has no tag or the `latest` tag; a digest pins it."""
    if "@" in image:
        return False
    # Only the last path segment holds the tag; earlier colons are registry ports.
    _, sep, tag = image.rsplit("/", maxsplit=1)[-1].partition(":")
    return not sep or tag == "latest"


def _image_name(image: str) -> str:
    """Drop the registry host and the tag, leaving the repository path people recognize.

    A first segment is a registry host when it holds a dot or a port, or is `localhost`,
    matching how Docker tells a host from a Docker Hub namespace. A transport prefix such
    as Podman's `docker://` is dropped first.
    """
    image = image.partition("://")[2] or image
    host, sep, rest = image.partition("/")
    if sep and ("." in host or ":" in host or host == "localhost"):
        image = rest
    return image.rsplit(":", maxsplit=1)[0] if ":" in image.rsplit("/", maxsplit=1)[-1] else image


def check_latest_tag(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag tasks whose image floats on `latest` or carries no tag.

    Returns:
        list[Finding]: One warning per unpinned task image.
    """
    return [
        job_finding(
            check="latest-tag",
            severity=FindingSeverity.WARNING,
            job_id=spec.id,
            job_name=spec.name,
            path=(group.name, task.name),
            problem=_image_name(image),
        )
        for spec, group, task in _live_tasks(snapshot)
        if isinstance(image := task.config.get("image"), str) and _is_unpinned(image)
    ]


def check_no_health_check(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag services that register with no health check.

    Returns:
        list[Finding]: One warning per unchecked service, at the group or task that
            registers it.
    """
    return [
        job_finding(
            check="no-health-check",
            severity=FindingSeverity.WARNING,
            job_id=spec.id,
            job_name=spec.name,
            path=path,
            problem=service.name or "(unnamed)",
        )
        for spec, group in _live_groups(snapshot)
        for path, services in [
            ((group.name,), group.services),
            *(((group.name, task.name), task.services) for task in group.tasks),
        ]
        for service in services
        if not service.checks
    ]


def check_default_resources(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag long-running tasks left at Nomad's default CPU and memory, which usually means unset.

    Short-lived lifecycle hooks are skipped: the defaults suit a task that exits in seconds.

    Returns:
        list[Finding]: One info finding per task left at the default resources.
    """
    return [
        job_finding(
            check="default-resources",
            severity=FindingSeverity.INFO,
            job_id=spec.id,
            job_name=spec.name,
            path=(group.name, task.name),
            problem="",
        )
        for spec, group, task in _live_tasks(snapshot)
        if not (task.lifecycle and task.lifecycle.is_short_lived)
        and task.resources is not None
        and task.resources.cpu == NOMAD_DEFAULT_CPU_MHZ
        and task.resources.memory_mb == NOMAD_DEFAULT_MEMORY_MB
    ]


def check_high_restarts(snapshot: DoctorSnapshot) -> list[Finding]:
    """Flag tasks of current allocations that are in a recent restart loop.

    Returns:
        list[Finding]: One warning per job, group, and task, with its highest count.
    """
    window_start_ns = snapshot.now_ns - DOCTOR_RESTART_WINDOW_SECONDS * 1_000_000_000
    worst: dict[tuple[str, str, str], int] = {}
    for alloc in snapshot.allocs:
        if not alloc.is_current:
            continue
        for task_name, state in alloc.task_states.items():
            last_restart_ns = state.last_restart_ns
            if (
                state.restarts >= DOCTOR_RESTART_THRESHOLD
                and last_restart_ns > 0
                and last_restart_ns >= window_start_ns
            ):
                key = (alloc.job_id, alloc.task_group, task_name)
                worst[key] = max(worst.get(key, 0), state.restarts)
    return [
        job_finding(
            check="high-restarts",
            severity=FindingSeverity.WARNING,
            job_id=job_id,
            job_name=snapshot.job_names.get(job_id, job_id),
            path=(group, task),
            problem=f"{restarts} restarts",
        )
        for (job_id, group, task), restarts in sorted(worst.items())
    ]
