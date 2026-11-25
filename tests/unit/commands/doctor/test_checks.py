"""Tests for the nd doctor check registry."""

from __future__ import annotations

from nd.commands.doctor.checks import run_checks
from nd.commands.doctor.findings import FindingSeverity
from nd.nomad.models.job import TaskResourcesSpec, TaskSpec
from tests.builders import (
    alloc_stub,
    doctor_snapshot,
    job_spec,
    job_stub,
    node_stub,
    task_group_spec,
    task_spec,
)


def test_run_checks_orders_by_severity() -> None:
    """Verify findings come back worst first."""
    # Given a default-resources task (info), a latest image (warning), and a failed alloc
    tasks = [
        TaskSpec(name="a", resources=TaskResourcesSpec(cpu=100, memory_mb=300)),
        task_spec("b", image="nginx:latest"),
    ]
    snapshot = doctor_snapshot(
        jobs=[job_stub()],
        job_specs=[job_spec(groups=[task_group_spec(tasks=tasks)])],
        allocs=[alloc_stub(client_status="failed")],
        job_file_paths={},
        job_directories_configured=False,
    )

    # When running every check
    findings = run_checks(snapshot)

    # Then critical comes before warning, before info
    assert [f.severity for f in findings] == [
        FindingSeverity.CRITICAL,
        FindingSeverity.WARNING,
        FindingSeverity.INFO,
    ]


def test_run_checks_groups_same_severity_by_registry_order() -> None:
    """Verify checks of equal severity keep registry order whatever their targets."""
    # Given a down node and a failed allocation on a job named after it alphabetically
    snapshot = doctor_snapshot(
        jobs=[job_stub("zzz")],
        allocs=[alloc_stub(job_id="zzz", client_status="failed")],
        nodes=[node_stub("a", status="down")],
        job_file_paths={},
        job_directories_configured=False,
    )

    # When running every check
    findings = run_checks(snapshot)

    # Then the failed allocation, registered first, comes first
    assert [f.check for f in findings] == ["failed-alloc", "node-down"]
