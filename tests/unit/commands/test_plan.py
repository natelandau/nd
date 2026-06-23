"""Tests for the nd plan command."""

from __future__ import annotations

from pathlib import Path

from nd.jobfiles import JobCandidate, JobFile, candidates_for


def test_candidates_for_flattens_names() -> None:
    """Verify each job name in each file becomes its own candidate."""
    files = [
        JobFile(path=Path("/j/a.hcl"), job_names=["web", "worker"]),
        JobFile(path=Path("/j/b.hcl"), job_names=["db"]),
    ]
    cands = candidates_for(files)
    assert [(c.name, c.file.path.name) for c in cands] == [
        ("web", "a.hcl"),
        ("worker", "a.hcl"),
        ("db", "b.hcl"),
    ]
    assert all(isinstance(c, JobCandidate) for c in cands)


def test_plan_no_directories_exits_clean(monkeypatch, tmp_path) -> None:
    """Verify plan exits 0 with a message when no job files are configured."""
    import nd.commands.plan as plan_mod

    monkeypatch.setattr(plan_mod, "load_job_directories", list)
    monkeypatch.setattr(plan_mod, "discover_job_files", lambda dirs: [])
    from typer.testing import CliRunner

    from nd.cli import app

    result = CliRunner().invoke(app, ["plan"])
    assert result.exit_code == 0
