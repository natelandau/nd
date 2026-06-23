"""Tests for the nd list command."""

from __future__ import annotations

from pathlib import Path

from nd.commands.list import ListRow, build_rows
from nd.jobfiles import JobFile


class _Job:
    def __init__(self, name: str, status: str, job_id: str = "") -> None:
        self.name = name
        self.status = status
        self.id = job_id or name


def test_build_rows_classifies_cluster_state() -> None:
    """Verify each job file is classified running / dead / not deployed."""
    # Given two files and a cluster where one job runs and one is dead
    files = [
        JobFile(path=Path("/j/web.hcl"), job_names=["web"]),
        JobFile(path=Path("/j/db.hcl"), job_names=["db"]),
        JobFile(path=Path("/j/new.hcl"), job_names=["new"]),
    ]
    jobs = [_Job("web", "running"), _Job("db", "dead")]
    # When
    rows = build_rows(files, jobs)
    # Then
    by_name = {r.job_name: r.cluster_status for r in rows}
    assert by_name == {"web": "running", "db": "dead", "new": "not deployed"}
    assert all(isinstance(r, ListRow) for r in rows)


def test_build_rows_sets_link_id_for_deployed_jobs() -> None:
    """Verify a deployed job carries its Nomad ID for linking and others do not."""
    # Given a deployed job whose ID differs from its name, plus a not-deployed file
    files = [
        JobFile(path=Path("/j/web.hcl"), job_names=["web"]),
        JobFile(path=Path("/j/new.hcl"), job_names=["new"]),
    ]
    jobs = [_Job("web", "running", job_id="web-prod")]
    # When
    rows = build_rows(files, jobs)
    # Then the deployed row links by Nomad ID; the not-deployed row has no link
    by_link = {r.job_name: r.link_id for r in rows}
    assert by_link == {"web": "web-prod", "new": None}


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
