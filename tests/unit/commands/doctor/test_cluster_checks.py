"""Tests for the allocation, node, file, and volume checks of nd doctor."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from nd.commands.doctor.cluster_checks import (
    check_blocked_eval,
    check_failed_alloc,
    check_job_drift,
    check_lost_alloc,
    check_no_local_file,
    check_node_down,
    check_unused_volume,
)
from nd.commands.doctor.findings import FindingSeverity, JobDrift
from nd.nomad.models.job import JobDiff, TaskDiff, TaskGroupDiff
from tests.builders import (
    agent_member,
    alloc_stub,
    doctor_snapshot,
    eval_stub,
    host_volume_stub,
    job_spec,
    job_stub,
    node_stub,
    volume_request,
)

if TYPE_CHECKING:
    from nd.nomad.models.allocation import AllocListStub
    from nd.nomad.models.job import JobListStub, JobSpec


@pytest.mark.parametrize(
    ("allocs", "expected_problems"),
    [
        ([alloc_stub(client_status="failed")], ["1 failed allocation"]),
        (
            [
                alloc_stub(alloc_id="a1", client_status="failed"),
                alloc_stub(alloc_id="a2", client_status="failed"),
            ],
            ["2 failed allocations"],
        ),
        ([alloc_stub(client_status="failed", next_allocation="a2")], []),
        ([alloc_stub(client_status="failed", desired_status="stop")], []),
        ([alloc_stub(client_status="lost")], []),
    ],
)
def test_check_failed_alloc(allocs: list[AllocListStub], expected_problems: list[str]) -> None:
    """Verify unreplaced failed allocations are one critical finding per job and group."""
    # Given the allocations
    snapshot = doctor_snapshot(jobs=[job_stub()], allocs=allocs)

    # When checking failed allocations
    findings = check_failed_alloc(snapshot)

    # Then stuck failures are counted on the group
    assert [f.problem for f in findings] == expected_problems
    assert all(
        (f.target, f.severity, f.job_id) == ("web/web", FindingSeverity.CRITICAL, "web")
        for f in findings
    )


@pytest.mark.parametrize(
    ("client_status", "desired_status", "next_allocation", "flagged"),
    [
        ("lost", "run", "", True),
        ("unknown", "run", "", True),
        ("lost", "run", "a2", False),
        ("unknown", "stop", "", False),
        ("failed", "run", "", False),
    ],
)
def test_check_lost_alloc(
    client_status: str, desired_status: str, next_allocation: str, *, flagged: bool
) -> None:
    """Verify lost or unknown allocations Nomad still wants and has not replaced are flagged."""
    # Given one allocation in the given state
    alloc = alloc_stub(
        client_status=client_status,
        desired_status=desired_status,
        next_allocation=next_allocation,
    )

    # When checking lost allocations
    findings = check_lost_alloc(doctor_snapshot(jobs=[job_stub()], allocs=[alloc]))

    # Then only a live, unreplaced lost allocation is a warning
    assert [(f.target, f.severity) for f in findings] == (
        [("web/web", FindingSeverity.WARNING)] if flagged else []
    )


@pytest.mark.parametrize(
    ("status", "flagged"),
    [("blocked", True), ("pending", True), ("complete", False)],
)
def test_check_blocked_eval(status: str, *, flagged: bool) -> None:
    """Verify a stuck evaluation is a warning on its job."""
    # Given one evaluation in the given status
    snapshot = doctor_snapshot(jobs=[job_stub()], evals=[eval_stub(status=status)])

    # When checking evaluations
    findings = check_blocked_eval(snapshot)

    # Then only a stuck evaluation is reported, on the job
    assert [(f.target, f.problem) for f in findings] == ([("web", status)] if flagged else [])


def test_check_node_down() -> None:
    """Verify nodes that are not ready and servers neither alive nor left are critical."""
    # Given one down node, one ready node, one failed, one alive, and one departed server
    snapshot = doctor_snapshot(
        nodes=[node_stub("n1", status="down"), node_stub("n2")],
        members=[
            agent_member("s1.global", status="failed"),
            agent_member("s2.global"),
            agent_member("s3.global", status="left"),
        ],
    )

    # When checking nodes
    findings = check_node_down(snapshot)

    # Then each unhealthy machine is one critical finding with no job attached
    assert [(f.target, f.problem) for f in findings] == [
        ("node:n1", "down"),
        ("server:s1", "server failed"),
    ]
    assert all(f.severity == FindingSeverity.CRITICAL and f.job_id is None for f in findings)


@pytest.mark.parametrize(
    ("job", "has_file", "configured", "unnamed_file", "expected"),
    [
        (job_stub(), False, True, False, [("web", "nd stop web")]),
        (job_stub(status="pending"), False, True, False, [("web", None)]),
        (job_stub(status="dead"), False, True, False, []),
        (job_stub(), True, True, False, []),
        (job_stub(), False, False, False, []),
        (job_stub("web/periodic-1700000000", parent_id="web"), False, True, False, []),
        (job_stub(), False, True, True, [("web", None)]),
    ],
)
def test_check_no_local_file(
    job: JobListStub,
    *,
    has_file: bool,
    configured: bool,
    unnamed_file: bool,
    expected: list[tuple[str, str | None]],
) -> None:
    """Verify a job with no local file is flagged, with a stop hint only while it runs.

    A periodic or parameterized child never has its own file, so it is not flagged. A
    file that names its job with a variable could declare any job, so no job gets a
    stop hint while one exists.
    """
    # Given one job with or without a matching local file
    snapshot = doctor_snapshot(
        jobs=[job],
        job_file_paths={"web": Path("/jobs/web.hcl")} if has_file else {},
        job_directories_configured=configured,
        unnamed_job_files=[Path("/jobs/templated.hcl")] if unnamed_file else [],
    )

    # When checking local files
    findings = check_no_local_file(snapshot)

    # Then only a live job without a file is reported, when job directories exist
    assert [(f.target, f.fix_hint) for f in findings] == expected
    assert all(f.severity == FindingSeverity.INFO for f in findings)


@pytest.mark.parametrize(
    ("volume_name", "specs", "local_specs", "expected"),
    [
        ("data", [job_spec(volumes={"v": volume_request()})], frozenset(), []),
        ("data", [job_spec(status="dead", volumes={"v": volume_request()})], frozenset(), []),
        ("data", [], frozenset({"data"}), [("volume:data", "nd volume delete data")]),
        ("data", [], frozenset(), [("volume:data", None)]),
        (
            "data",
            [job_spec(volumes={"v": volume_request(request_type="csi")})],
            frozenset(),
            [("volume:data", None)],
        ),
        ("data[1]", [job_spec(volumes={"v": volume_request(per_alloc=True)})], frozenset(), []),
        (
            "data[1]",
            [job_spec(volumes={"v": volume_request()})],
            frozenset(),
            [("volume:data[1]", None)],
        ),
    ],
)
def test_check_unused_volume(
    volume_name: str,
    specs: list[JobSpec],
    local_specs: frozenset[str],
    expected: list[tuple[str, str | None]],
) -> None:
    """Verify a host volume no job requests is flagged, with a delete hint only for local specs."""
    # Given one volume registered on two nodes, and the given job specs
    snapshot = doctor_snapshot(
        job_specs=specs,
        volumes=[
            host_volume_stub(name=volume_name, node_id="n1"),
            host_volume_stub(name=volume_name, node_id="n2"),
        ],
        volume_spec_names=local_specs,
    )

    # When checking volume usage
    findings = check_unused_volume(snapshot)

    # Then an unrequested volume is reported once, by name
    assert [(f.target, f.fix_hint) for f in findings] == expected


def _group(name: str, *tasks: str, type_: str = "Edited") -> TaskGroupDiff:
    """Build a group diff whose listed tasks are edited."""
    return TaskGroupDiff(
        name=name, type=type_, tasks_raw=[TaskDiff(name=t, type="Edited") for t in tasks]
    )


_EDITED = FindingSeverity.WARNING


@pytest.mark.parametrize(
    ("drift", "binary_found", "expected"),
    [
        pytest.param(JobDrift(diff=JobDiff(type="None")), True, [], id="unchanged"),
        pytest.param(
            JobDrift(diff=JobDiff(type="Edited", task_groups_raw=[_group("app", "server")])),
            True,
            [(_EDITED, "web", "app/server", "nd plan web")],
            id="one-task",
        ),
        pytest.param(
            JobDrift(
                diff=JobDiff(
                    type="Edited",
                    task_groups_raw=[_group("app", "a", "b"), _group("db", type_="None")],
                )
            ),
            True,
            [(_EDITED, "web", "app", "nd plan web")],
            id="several-tasks-one-group",
        ),
        pytest.param(
            JobDrift(diff=JobDiff(type="Edited", task_groups_raw=[_group("app"), _group("db")])),
            True,
            [(_EDITED, "web", "2 groups", "nd plan web")],
            id="two-groups",
        ),
        pytest.param(
            JobDrift(diff=JobDiff(type="Edited", task_groups_raw=[_group("app", "app")])),
            True,
            [(_EDITED, "web", "app", "nd plan web")],
            id="task-named-like-group",
        ),
        pytest.param(
            JobDrift(diff=JobDiff(type="Edited")),
            True,
            [(_EDITED, "web", "job settings", "nd plan web")],
            id="job-settings",
        ),
        pytest.param(
            JobDrift(
                diff=JobDiff(type="Edited", task_groups_raw=[_group("a"), _group("b"), _group("c")])
            ),
            True,
            [(_EDITED, "web", "3 groups", "nd plan web")],
            id="three-groups",
        ),
        pytest.param(
            JobDrift(error="bad file"),
            True,
            [(_EDITED, "web", "plan failed: bad file", None)],
            id="error",
        ),
        pytest.param(
            None,
            False,
            [(FindingSeverity.INFO, "nomad", "binary not found; drift not checked", None)],
            id="binary-missing",
        ),
    ],
)
def test_check_job_drift(
    drift: JobDrift | None,
    *,
    binary_found: bool,
    expected: list[tuple[FindingSeverity, str, str, str | None]],
) -> None:
    """Verify a running job that differs from its file is flagged with what changed."""
    # Given web's plan result, or a missing nomad binary
    snapshot = doctor_snapshot(
        jobs=[job_stub("web")],
        job_drift={"web": drift} if drift else {},
        nomad_binary_found=binary_found,
    )

    # When checking drift
    findings = check_job_drift(snapshot)

    # Then each finding names its target, what changed, and the command to review it
    assert [(f.severity, f.target, f.problem, f.fix_hint) for f in findings] == expected
