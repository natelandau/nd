"""Tests for the nd doctor command wiring and snapshot collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nd.binary.env import NomadBinaryError
from nd.commands import doctor
from nd.commands.doctor.snapshot import collect_snapshot
from nd.nomad import NomadConfig
from nd.nomad.models.job import JobDiff
from tests.builders import (
    agent_member,
    compiled_job,
    job_diff,
    job_plan,
    job_spec,
    job_stub,
    node_stub,
    task_spec,
    to_payload,
)
from tests.helpers import run_with_client

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

    import respx

    from nd.commands.doctor.findings import DoctorSnapshot, JobDrift
    from nd.nomad import NomadClient
    from nd.nomad.models.job import JobSpec


@pytest.fixture
def cluster(httpx2_mock: respx.Router, nomad_env: str) -> respx.Router:
    """Mock every endpoint nd doctor reads: one ready node, one alive server, no jobs."""
    httpx2_mock.get(f"{nomad_env}/v1/nodes", name="nodes").respond(
        json=[to_payload(node_stub("n1"))]
    )
    httpx2_mock.get(f"{nomad_env}/v1/jobs", name="jobs").respond(json=[])
    httpx2_mock.get(f"{nomad_env}/v1/allocations").respond(json=[])
    httpx2_mock.get(f"{nomad_env}/v1/agent/members").respond(
        json={"Members": [to_payload(agent_member("s1.global"))]}
    )
    httpx2_mock.get(f"{nomad_env}/v1/evaluations").respond(json=[])
    httpx2_mock.get(f"{nomad_env}/v1/volumes", params={"type": "host"}, name="volumes").respond(
        json=[]
    )
    return httpx2_mock


def _deploy(cluster: respx.Router, nomad_env: str, *specs: JobSpec) -> None:
    """Serve the given specs from the jobs listing and from each job's own endpoint."""
    cluster.routes["jobs"].respond(
        json=[to_payload(job_stub(spec.name, status=spec.status or "running")) for spec in specs]
    )
    for spec in specs:
        cluster.get(f"{nomad_env}/v1/job/{spec.name}").respond(json=to_payload(spec))


def _drift_by_name(snapshot: DoctorSnapshot) -> dict[str, JobDrift]:
    """Key the snapshot's plan results by job name, for tests with unique names."""
    return {job.name: drift for job, drift in snapshot.job_drift.items()}


async def _collect(client: NomadClient) -> DoctorSnapshot:
    """Collect a snapshot with the test's resolved config."""
    return await collect_snapshot(client, NomadConfig.resolve())


def _compiled(path: Path) -> bytes:
    """Compile a job file to a job whose ID is the file's stem."""
    return compiled_job(path.stem)


def _plan(cluster: respx.Router, nomad_env: str, job_id: str, diff: JobDiff) -> respx.Route:
    """Serve one job's plan with the given diff."""
    return cluster.post(f"{nomad_env}/v1/job/{job_id}/plan").respond(json=job_plan(diff))


_DEFAULT_RESOURCES = task_spec(image=None, cpu=100, memory_mb=300)


@pytest.mark.parametrize(
    ("specs", "node_status", "expected_exit"),
    [
        pytest.param([job_spec("web", tasks=[task_spec()])], "ready", 0, id="healthy"),
        pytest.param([job_spec("web", tasks=[_DEFAULT_RESOURCES])], "ready", 0, id="info-only"),
        pytest.param(
            [job_spec("web", tasks=[task_spec(image="nginx:latest")])], "ready", 1, id="warning"
        ),
        pytest.param([], "down", 1, id="critical"),
    ],
)
def test_doctor_exits_by_severity(
    cluster: respx.Router,
    nomad_env: str,
    typer_runner,
    specs: list[JobSpec],
    node_status: str,
    expected_exit: int,
) -> None:
    """Verify nd doctor fails only when a warning or critical finding exists."""
    # Given a cluster with the given jobs and node status
    _deploy(cluster, nomad_env, *specs)
    cluster.routes["nodes"].respond(json=[to_payload(node_stub("n1", status=node_status))])

    # When running nd doctor
    result = typer_runner.invoke(doctor.app, [])

    # Then the exit code reflects the worst severity
    assert result.exit_code == expected_exit


def test_doctor_name_filter_drops_other_findings(
    cluster: respx.Router, nomad_env: str, typer_runner
) -> None:
    """Verify NAME keeps only findings on matching jobs and drops cluster findings."""
    # Given a warning on web, a clean db, and a down node
    _deploy(
        cluster,
        nomad_env,
        job_spec("web", tasks=[task_spec(image="nginx:latest")]),
        job_spec("db", tasks=[task_spec()]),
    )
    cluster.routes["nodes"].respond(json=[to_payload(node_stub("n1", status="down"))])

    # When running nd doctor for db, then for part of web in capitals
    db_result = typer_runner.invoke(doctor.app, ["db"])
    web_result = typer_runner.invoke(doctor.app, ["WE"])

    # Then only web's own warning fails the command, matched ignoring case
    assert db_result.exit_code == 0
    assert web_result.exit_code == 1


def test_doctor_name_matching_no_job_fails(
    cluster: respx.Router, nomad_env: str, typer_runner
) -> None:
    """Verify a NAME that matches no job fails instead of reporting no problems."""
    # Given a cluster running only web
    _deploy(cluster, nomad_env, job_spec("web", tasks=[task_spec()]))

    # When running nd doctor for a job that does not exist
    result = typer_runner.invoke(doctor.app, ["nope"])

    # Then the command fails
    assert result.exit_code == 1


def test_doctor_skips_job_that_vanishes(
    cluster: respx.Router, nomad_env: str, typer_runner
) -> None:
    """Verify a job purged between the listing and its fetch is skipped, not fatal."""
    # Given a listed job whose own endpoint returns 404
    cluster.routes["jobs"].respond(json=[to_payload(job_stub("web"))])
    cluster.get(f"{nomad_env}/v1/job/web").respond(404, text="job not found")

    # When running nd doctor
    result = typer_runner.invoke(doctor.app, [])

    # Then it completes without that job's spec
    assert result.exit_code == 0


@pytest.mark.usefixtures("cluster")
def test_collect_snapshot_without_volumes_endpoint(cluster: respx.Router) -> None:
    """Verify a token without volume access still gets every other check."""
    # Given a cluster whose volumes endpoint refuses the token
    cluster.routes["volumes"].respond(403, text="Permission denied")

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then the snapshot holds no volumes and the rest of the cluster
    assert snapshot.volumes == []
    assert [node.name for node in snapshot.nodes] == ["n1"]


def test_collect_snapshot_reads_local_files(
    cluster: respx.Router, nomad_env: str, job_files, volume_files
) -> None:
    """Verify the snapshot maps job names to local files and records local volume specs."""
    # Given a local job file for web and a local volume spec for data
    path = job_files("web.hcl", "web")
    volume_files("data")
    _deploy(cluster, nomad_env, job_spec("web", tasks=[task_spec()]))

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then local files and specs are available to the checks
    assert snapshot.job_file_paths == {"web": path}
    assert snapshot.job_directories_configured is True
    assert snapshot.volume_spec_names == frozenset({"data"})
    assert [spec.name for spec in snapshot.job_specs] == ["web"]


def test_collect_snapshot_skips_child_job_specs(cluster: respx.Router, nomad_env: str) -> None:
    """Verify a periodic child's spec is not fetched, since its parent's spec covers it."""
    # Given a periodic parent and one launched child, with only the parent's spec served
    parent = job_spec("backup", tasks=[task_spec()])
    cluster.routes["jobs"].respond(
        json=[
            to_payload(job_stub("backup")),
            to_payload(job_stub("backup/periodic-1700000000", parent_id="backup")),
        ]
    )
    cluster.get(f"{nomad_env}/v1/job/backup").respond(json=to_payload(parent))

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then only the parent's spec is fetched
    assert [spec.name for spec in snapshot.job_specs] == ["backup"]


def test_collect_snapshot_records_files_with_unreadable_job_names(
    cluster: respx.Router, job_files
) -> None:
    """Verify a job file that names its job with a variable is recorded as unnamed."""
    # Given a job file whose only job name is a variable
    path = job_files("templated.hcl", "${var.name}")

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then the file is recorded so checks know a job may come from it
    assert snapshot.unnamed_job_files == [path]


def test_collect_snapshot_plans_running_jobs_with_files(
    cluster: respx.Router, nomad_env: str, job_files, fake_nomad_binary: MagicMock
) -> None:
    """Verify only running, file-backed, non-child jobs are planned against their files."""
    # Given files for web, old (dead), and backup (with a periodic child), plus an orphan
    job_files("web.hcl", "web")
    old_file = job_files("old.hcl", "old")
    job_files("backup.hcl", "backup")
    specs = [
        job_spec("web", tasks=[task_spec()]),
        job_spec("old", status="dead", tasks=[task_spec()]),
        job_spec("backup", tasks=[task_spec()]),
        job_spec("orphan", tasks=[task_spec()]),
    ]
    cluster.routes["jobs"].respond(
        json=[
            *(to_payload(job_stub(s.name, status=s.status or "running")) for s in specs),
            to_payload(job_stub("backup/periodic-1", parent_id="backup")),
        ]
    )
    for spec in specs:
        cluster.get(f"{nomad_env}/v1/job/{spec.name}").respond(json=to_payload(spec))
    fake_nomad_binary.compile_job.side_effect = _compiled
    _plan(cluster, nomad_env, "web", job_diff())
    _plan(cluster, nomad_env, "backup", job_diff(type_="None"))

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then web and backup are planned and the dead job's file is never compiled
    drift = _drift_by_name(snapshot)
    assert set(drift) == {"web", "backup"}
    web_diff = drift["web"]
    assert isinstance(web_diff, JobDiff)
    assert web_diff.is_changed
    assert all(call.args[0] != old_file for call in fake_nomad_binary.compile_job.call_args_list)


def test_collect_snapshot_records_compile_error(
    cluster: respx.Router, nomad_env: str, job_files, fake_nomad_binary: MagicMock
) -> None:
    """Verify a job file that fails to compile is recorded as the compiler's first error line."""
    # Given a running web whose file fails to compile
    job_files("web.hcl", "web")
    _deploy(cluster, nomad_env, job_spec("web", tasks=[task_spec()]))
    fake_nomad_binary.compile_job.side_effect = NomadBinaryError(
        "`nomad job run -output web.hcl` failed", detail="Error parsing job file\nline 3"
    )

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then web's drift is the compiler's error, without the command
    assert _drift_by_name(snapshot) == {"web": "Error parsing job file"}


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        pytest.param(400, "invalid job", "invalid job", id="bad-request"),
        pytest.param(
            400,
            "1 error occurred:\n\t* Task group app validation failed\n\n",
            "Task group app validation failed",
            id="multi-error",
        ),
        pytest.param(500, "", "Nomad returned HTTP 500", id="server-error"),
        pytest.param(200, "not json", "Failed to decode JobPlanResponse", id="bad-response"),
    ],
)
def test_collect_snapshot_records_rejected_plan(
    cluster: respx.Router,
    nomad_env: str,
    job_files,
    fake_nomad_binary: MagicMock,
    status: int,
    body: str,
    expected: str,
) -> None:
    """Verify a rejected or unreadable plan is recorded as the reason instead of failing doctor."""
    # Given a running web whose plan Nomad rejects
    job_files("web.hcl", "web")
    _deploy(cluster, nomad_env, job_spec("web", tasks=[task_spec()]))
    fake_nomad_binary.compile_job.side_effect = _compiled
    cluster.post(f"{nomad_env}/v1/job/web/plan").respond(status, text=body)

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then web's drift starts with the line that states Nomad's reason
    drift = _drift_by_name(snapshot)["web"]
    assert isinstance(drift, str)
    assert drift.startswith(expected)


def test_collect_snapshot_without_plan_permission(
    cluster: respx.Router, nomad_env: str, job_files, fake_nomad_binary: MagicMock
) -> None:
    """Verify a token that cannot plan skips drift once instead of failing every job."""
    # Given two running jobs with files and a token the plan endpoint refuses
    job_files("web.hcl", "web")
    job_files("db.hcl", "db")
    _deploy(
        cluster,
        nomad_env,
        job_spec("web", tasks=[task_spec()]),
        job_spec("db", tasks=[task_spec()]),
    )
    fake_nomad_binary.compile_job.side_effect = _compiled
    for job_id in ("web", "db"):
        cluster.post(f"{nomad_env}/v1/job/{job_id}/plan").respond(403, text="Permission denied")

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then drift is recorded as not checked rather than as two failures
    assert snapshot.job_drift == {}
    assert snapshot.drift_not_checked


def test_collect_snapshot_without_nomad_binary(
    cluster: respx.Router, nomad_env: str, job_files
) -> None:
    """Verify a missing nomad binary skips drift instead of failing the snapshot."""
    # Given a running web with a file and no nomad binary
    job_files("web.hcl", "web")
    _deploy(cluster, nomad_env, job_spec("web", tasks=[task_spec()]))

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then drift is recorded as not checked, with the reason
    assert snapshot.job_drift == {}
    assert snapshot.drift_not_checked


def test_collect_snapshot_skips_binary_when_nothing_to_plan(
    cluster: respx.Router, nomad_env: str
) -> None:
    """Verify the binary is not needed when no running job has a local file."""
    # Given a running job, no job directories, and no nomad binary
    _deploy(cluster, nomad_env, job_spec("web", tasks=[task_spec()]))

    # When collecting the snapshot
    snapshot = run_with_client(_collect)

    # Then the missing binary is not reported
    assert snapshot.job_drift == {}
    assert snapshot.drift_not_checked is None


def test_doctor_fails_on_drift(
    cluster: respx.Router, nomad_env: str, job_files, fake_nomad_binary: MagicMock, typer_runner
) -> None:
    """Verify a running job that differs from its local file fails nd doctor."""
    # Given a running web whose plan shows a change
    job_files("web.hcl", "web")
    _deploy(cluster, nomad_env, job_spec("web", tasks=[task_spec()]))
    fake_nomad_binary.compile_job.side_effect = _compiled
    _plan(cluster, nomad_env, "web", job_diff())

    # When running nd doctor
    result = typer_runner.invoke(doctor.app, [])

    # Then the drift warning fails the command
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
