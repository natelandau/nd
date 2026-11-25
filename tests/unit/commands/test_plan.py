"""Tests for the nd plan command."""

from __future__ import annotations

from nd.cli import app
from nd.commands import plan as plan_module


def test_plan_no_directories_exits_clean(monkeypatch, typer_runner) -> None:
    """Verify plan exits 0 with a message when no job files are configured."""
    # Given no configured job directories and so no job files
    monkeypatch.setattr(plan_module, "load_job_directories", list)
    monkeypatch.setattr(plan_module, "discover_job_files", lambda dirs: [])

    # When invoking plan
    result = typer_runner.invoke(app, ["plan"])

    # Then it exits cleanly
    assert result.exit_code == 0
