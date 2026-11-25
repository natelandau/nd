"""Tests for the job spec checks of nd doctor."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nd.commands.doctor.findings import FindingSeverity
from nd.commands.doctor.job_checks import (
    check_default_resources,
    check_high_restarts,
    check_latest_tag,
    check_no_health_check,
)
from nd.nomad.models.job import (
    ServiceCheckSpec,
    ServiceSpec,
    TaskLifecycleSpec,
    TaskResourcesSpec,
    TaskSpec,
)
from tests.builders import (
    alloc_stub,
    doctor_snapshot,
    job_spec,
    job_stub,
    task_group_spec,
    task_spec,
    task_state,
)

NOW_NS = int(datetime(2026, 11, 24, 12, tzinfo=UTC).timestamp()) * 1_000_000_000


@pytest.mark.parametrize(
    ("image", "status", "expected_detail"),
    [
        ("nginx", "running", "nginx"),
        ("nginx:latest", "running", "nginx"),
        ("registry.local:5000/app", "running", "app"),
        ("ghcr.io/advplyr/audiobookshelf:latest", "running", "advplyr/audiobookshelf"),
        ("linuxserver/sonarr:latest", "running", "linuxserver/sonarr"),
        ("localhost/app", "running", "app"),
        ("docker://docker.io/library/nginx", "running", "library/nginx"),
        ("nginx:1.27", "running", None),
        ("nginx@sha256:abc", "running", None),
        (None, "running", None),
        ("nginx:latest", "dead", None),
    ],
)
def test_check_latest_tag(image: str | None, status: str, expected_detail: str | None) -> None:
    """Verify an unpinned image on a live job is flagged and named without registry or tag."""
    # Given a job whose one task uses the given image
    spec = job_spec(status=status, groups=[task_group_spec(tasks=[task_spec(image=image)])])

    # When checking image tags
    findings = check_latest_tag(doctor_snapshot(job_specs=[spec]))

    # Then only an unpinned image on a live job is a warning on the task, named briefly
    assert [(f.target, f.severity, f.problem) for f in findings] == (
        [("web/web/app", FindingSeverity.WARNING, expected_detail)] if expected_detail else []
    )


_UNCHECKED = ServiceSpec(name="web")
_CHECKED = ServiceSpec(name="web", checks_raw=[ServiceCheckSpec()])


@pytest.mark.parametrize(
    ("group_services", "task_services", "expected_targets"),
    [
        ([_UNCHECKED], None, ["web/web"]),
        (None, [_UNCHECKED], ["web/web/app"]),
        ([_CHECKED], [_CHECKED], []),
        (None, None, []),
    ],
)
def test_check_no_health_check(
    group_services: list[ServiceSpec] | None,
    task_services: list[ServiceSpec] | None,
    expected_targets: list[str],
) -> None:
    """Verify each service with no check is flagged, and a group with no service is not."""
    # Given a job with the given group and task services
    group = task_group_spec(services=group_services, tasks=[task_spec(services=task_services)])
    snapshot = doctor_snapshot(job_specs=[job_spec(groups=[group])])

    # When checking health checks
    findings = check_no_health_check(snapshot)

    # Then each unchecked service is named at the level that registers it
    assert [f.target for f in findings] == expected_targets


_DEFAULTS = TaskResourcesSpec(cpu=100, memory_mb=300)


@pytest.mark.parametrize(
    ("resources", "lifecycle", "flagged"),
    [
        (_DEFAULTS, None, True),
        (TaskResourcesSpec(cpu=500, memory_mb=512), None, False),
        (TaskResourcesSpec(cpu=100, memory_mb=512), None, False),
        (None, None, False),
        (TaskResourcesSpec(cpu=None, memory_mb=None), None, False),
        (_DEFAULTS, TaskLifecycleSpec(hook="prestart"), False),
        (_DEFAULTS, TaskLifecycleSpec(hook="poststop", sidecar=False), False),
        (_DEFAULTS, TaskLifecycleSpec(hook="prestart", sidecar=True), True),
    ],
)
def test_check_default_resources(
    resources: TaskResourcesSpec | None, lifecycle: TaskLifecycleSpec | None, *, flagged: bool
) -> None:
    """Verify a long-running task left at Nomad's default CPU and memory is an info finding."""
    # Given a job whose task has the given resources and lifecycle
    task = TaskSpec(name="app", resources=resources, lifecycle=lifecycle)
    snapshot = doctor_snapshot(job_specs=[job_spec(groups=[task_group_spec(tasks=[task])])])

    # When checking resources
    findings = check_default_resources(snapshot)

    # Then only a main task or sidecar with default or missing resources is flagged
    assert [(f.target, f.severity) for f in findings] == (
        [("web/web/app", FindingSeverity.INFO)] if flagged else []
    )


@pytest.mark.parametrize(
    ("restarts", "last_restart", "desired_status", "expected_problems"),
    [
        (5, "2026-11-24T11:00:00Z", "run", ["5 restarts"]),
        (4, "2026-11-24T11:00:00Z", "run", []),
        (5, "2026-11-22T12:00:00Z", "run", []),
        (5, "", "run", []),
        (5, "2026-11-24T11:00:00Z", "stop", []),
    ],
)
@pytest.mark.parametrize(("next_allocation", "reported"), [("", True), ("a2", False)])
def test_check_high_restarts(
    restarts: int,
    last_restart: str,
    desired_status: str,
    expected_problems: list[str],
    next_allocation: str,
    *,
    reported: bool,
) -> None:
    """Verify a live task that restarted often and recently is flagged."""
    # Given an allocation, replaced or not, whose task restarted the given number of times
    alloc = alloc_stub(
        desired_status=desired_status,
        next_allocation=next_allocation,
        task_states={"app": task_state(restarts=restarts, last_restart=last_restart)},
    )
    snapshot = doctor_snapshot(jobs=[job_stub()], allocs=[alloc], now_ns=NOW_NS)

    # When checking restarts
    findings = check_high_restarts(snapshot)

    # Then only a recent restart loop on a live, unreplaced allocation is reported
    assert [f.problem for f in findings] == (expected_problems if reported else [])
    assert all(f.target == "web/web/app" and f.job_name == "web" for f in findings)


def test_check_high_restarts_reports_highest_count_once() -> None:
    """Verify two allocations of one task produce one finding with the highest count."""
    # Given two live allocations of the same task, both in a recent restart loop
    allocs = [
        alloc_stub(
            alloc_id=alloc_id,
            task_states={"app": task_state(restarts=count, last_restart="2026-11-24T11:00:00Z")},
        )
        for alloc_id, count in (("a1", 6), ("a2", 9))
    ]
    snapshot = doctor_snapshot(jobs=[job_stub()], allocs=allocs, now_ns=NOW_NS)

    # When checking restarts
    findings = check_high_restarts(snapshot)

    # Then the task is reported once, with its worst count
    assert [f.problem for f in findings] == ["9 restarts"]
