"""Tests for the nd list command."""

from __future__ import annotations

from pathlib import Path

import msgspec
import pytest

from nd.commands.list import ListRow, build_rows
from nd.jobfiles import JobFile
from tests.builders import job_stub


@pytest.mark.parametrize(
    ("hide_running", "expected"),
    [
        pytest.param(False, {"web": "running", "db": "dead", "new": "not deployed"}, id="all"),
        pytest.param(True, {"db": "dead", "new": "not deployed"}, id="hide-running"),
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
    assert all(isinstance(r, ListRow) for r in rows)


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
    """Verify a job file with no resolved name is surfaced as a '?' row, not dropped."""
    # Given a job file whose name could not be parsed (e.g. interpolated)
    files = [JobFile(path=Path("/j/tpl.hcl"), job_names=[])]

    # When building rows against an empty cluster
    rows = build_rows(files, [])

    # Then the file still appears, named '?', classified not deployed with no link
    assert len(rows) == 1
    assert rows[0].job_name == "?"
    assert rows[0].cluster_status == "not deployed"
    assert rows[0].link_id is None
