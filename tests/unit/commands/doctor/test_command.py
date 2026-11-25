"""Tests for the nd doctor command wiring and snapshot collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nd.commands import doctor
from nd.commands.doctor.snapshot import collect_snapshot
from tests.builders import (
    agent_member,
    job_spec,
    job_stub,
    node_stub,
    task_spec,
    to_payload,
)
from tests.helpers import run_with_client

if TYPE_CHECKING:
    import respx

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
    snapshot = run_with_client(collect_snapshot)

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
    snapshot = run_with_client(collect_snapshot)

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
    snapshot = run_with_client(collect_snapshot)

    # Then only the parent's spec is fetched
    assert [spec.name for spec in snapshot.job_specs] == ["backup"]


def test_collect_snapshot_records_files_with_unreadable_job_names(
    cluster: respx.Router, job_files
) -> None:
    """Verify a job file that names its job with a variable is recorded as unnamed."""
    # Given a job file whose only job name is a variable
    path = job_files("templated.hcl", "${var.name}")

    # When collecting the snapshot
    snapshot = run_with_client(collect_snapshot)

    # Then the file is recorded so checks know a job may come from it
    assert snapshot.unnamed_job_files == [path]
