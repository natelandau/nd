"""Tests for the nd list command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec
import pytest

from nd.cli import app
from nd.commands.list import NOT_DEPLOYED, build_rows
from nd.jobfiles import JobFile
from nd.nomad import NomadError
from tests.builders import job_stub, to_payload
from tests.helpers import NOMAD_TEST_ADDR, capture_output

if TYPE_CHECKING:
    from collections.abc import Callable

    import respx


@pytest.mark.parametrize(
    ("hide_running", "expected"),
    [
        pytest.param(False, {"web": "running", "db": "dead", "new": NOT_DEPLOYED}, id="all"),
        pytest.param(True, {"db": "dead", "new": NOT_DEPLOYED}, id="hide-running"),
    ],
)
def test_build_rows_classifies_cluster_state(
    *, hide_running: bool, expected: dict[str, str]
) -> None:
    """Verify files are classified by cluster state and hide_running drops only running jobs."""
    # Given files where one job runs, one is dead, and one is not deployed
    files = [
        JobFile(path=Path("/j/web.hcl"), job_names=["web"]),
        JobFile(path=Path("/j/db.hcl"), job_names=["db"]),
        JobFile(path=Path("/j/new.hcl"), job_names=["new"]),
    ]
    jobs = [job_stub("web", status="running"), job_stub("db", status="dead")]

    # When building rows
    rows = build_rows(files, jobs, hide_running=hide_running)

    # Then each remaining row carries its cluster status
    assert {r.job_name: r.cluster_status for r in rows} == expected


def test_build_rows_sets_link_id_for_deployed_jobs() -> None:
    """Verify a deployed job carries its Nomad ID for linking and others do not."""
    # Given a deployed job whose ID differs from its name, plus a not-deployed file
    files = [
        JobFile(path=Path("/j/web.hcl"), job_names=["web"]),
        JobFile(path=Path("/j/new.hcl"), job_names=["new"]),
    ]
    jobs = [msgspec.structs.replace(job_stub("web"), id="web-prod")]

    # When building rows
    rows = build_rows(files, jobs)

    # Then the deployed row links by Nomad ID; the not-deployed row has no link
    assert {r.job_name: r.link_id for r in rows} == {"web": "web-prod", "new": None}


def test_build_rows_surfaces_unresolved_job_name() -> None:
    """Verify a job file with no resolved name is surfaced as a nameless row, not dropped."""
    # Given a job file whose name could not be parsed (e.g. interpolated)
    files = [JobFile(path=Path("/j/tpl.hcl"), job_names=[])]

    # When building rows against an empty cluster
    rows = build_rows(files, [])

    # Then the file still appears with no name, classified not deployed with no link
    assert len(rows) == 1
    assert rows[0].job_name is None
    assert rows[0].cluster_status == NOT_DEPLOYED
    assert rows[0].link_id is None


@pytest.mark.usefixtures("nomad_env")
def test_list_command_shows_each_job_file_with_cluster_status(
    job_files: Callable[..., Path], httpx2_mock: respx.Router, typer_runner
) -> None:
    """Verify `nd list` reads the configured job files and shows each one's cluster status."""
    # Given two job files, of which only `web` is deployed
    job_files("web.hcl", "web")
    job_files("new.hcl", "new")
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("web"))])
    console = capture_output(width=200)

    # When listing job files
    result = typer_runner.invoke(app, ["list"])

    # Then both files appear with their status
    assert result.exit_code == 0
    text = console.export_text()
    assert "web.hcl" in text
    assert "running" in text
    assert "new.hcl" in text
    assert NOT_DEPLOYED in text


@pytest.mark.usefixtures("nomad_env")
@pytest.mark.parametrize(
    "has_files", [pytest.param(True, id="files"), pytest.param(False, id="empty")]
)
def test_list_command_prints_json(
    *, has_files: bool, job_files: Callable[..., Path], httpx2_mock: respx.Router, typer_runner
) -> None:
    """Verify `nd list --json` prints only a JSON array of rows on stdout, even at -vv."""
    # Given either two job files with only `web` deployed, or no job files at all
    expected = []
    if has_files:
        new = job_files("new.hcl", "new")
        web = job_files("web.hcl", "web")
        expected = [
            {"job": "new", "status": NOT_DEPLOYED, "file": str(new)},
            {"job": "web", "status": "running", "file": str(web)},
        ]
    jobs = [to_payload(job_stub("web"))] if has_files else []
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=jobs)

    # When listing as JSON with trace output enabled
    result = typer_runner.invoke(app, ["list", "--json", "-vv"])

    # Then stdout holds exactly the JSON rows
    assert result.exit_code == 0
    assert json.loads(result.stdout) == expected


@pytest.mark.usefixtures("nomad_env")
def test_list_command_json_leaves_stdout_empty_on_nomad_error(
    job_files: Callable[..., Path], httpx2_mock: respx.Router, typer_runner
) -> None:
    """Verify a Nomad failure under --json exits non-zero with nothing on stdout."""
    # Given a job file and a Nomad agent that fails the jobs request
    job_files("web.hcl", "web")
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(500, text="boom")

    # When listing as JSON
    result = typer_runner.invoke(app, ["list", "--json"])

    # Then the error propagates and stdout stays empty
    assert result.exit_code == 1
    assert isinstance(result.exception, NomadError)
    assert result.stdout == ""
