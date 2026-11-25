"""Tests for the nd plan command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nd.binary import NomadBinary, NomadBinaryError
from nd.cli import app
from nd.commands import plan as plan_module

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from unittest.mock import MagicMock

    import pytest
    from pytest_mock import MockerFixture


def _patch_binary(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> MagicMock:
    """Replace the nomad binary with a mock and return it for call assertions."""
    nomad = mocker.MagicMock(spec=NomadBinary)
    monkeypatch.setattr(plan_module.NomadBinary, "create", classmethod(lambda _cls, _cfg: nomad))
    return nomad


def _select_all_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer the job multi-select by picking every candidate offered."""

    async def _select(candidates: list[object], *_args: object, **_kwargs: object) -> list[object]:
        return candidates

    monkeypatch.setattr(plan_module, "select_targets", _select)


def test_plan_no_job_files_exits_clean(typer_runner) -> None:
    """Verify plan exits 0 with a message when no job files are configured."""
    # Given no configured job directories
    # When invoking plan
    result = typer_runner.invoke(app, ["plan"])

    # Then it exits cleanly
    assert result.exit_code == 0


def test_plan_validates_and_plans_each_file_once(
    job_files: Callable[..., Path], monkeypatch, mocker, typer_runner
) -> None:
    """Verify a file declaring several jobs is validated and planned once, not per job."""
    # Given one file that declares two jobs, both selected
    path = job_files("app.hcl", "app-web", "app-worker")
    nomad = _patch_binary(monkeypatch, mocker)
    _select_all_matches(monkeypatch)

    # When planning both of its jobs
    result = typer_runner.invoke(app, ["plan"])

    # Then the file is validated and planned exactly once and the command succeeds
    assert result.exit_code == 0
    nomad.validate.assert_called_once_with(path)
    nomad.plan.assert_called_once_with(path)


def test_plan_validation_failure_exits_non_zero_and_plans_the_rest(
    job_files: Callable[..., Path], monkeypatch, mocker, typer_runner
) -> None:
    """Verify one invalid file fails the command without stopping the other plans."""
    # Given two job files, the first of which fails validation
    bad = job_files("a-bad.hcl", "svc-bad")
    good = job_files("b-good.hcl", "svc-good")
    nomad = _patch_binary(monkeypatch, mocker)
    _select_all_matches(monkeypatch)

    def _validate(path: Path) -> None:
        if path == bad:
            msg = f"invalid {path}"
            raise NomadBinaryError(msg)

    nomad.validate.side_effect = _validate

    # When planning both
    result = typer_runner.invoke(app, ["plan"])

    # Then the command fails, and the valid file is still planned
    assert result.exit_code == 1
    nomad.plan.assert_called_once_with(good)


def test_plan_missing_binary_exits_non_zero(job_files: Callable[..., Path], typer_runner) -> None:
    """Verify plan fails cleanly when the nomad binary is not on PATH."""
    # Given a job file and no nomad binary (the test sandbox hides it)
    job_files("web.hcl", "web")

    # When planning it
    result = typer_runner.invoke(app, ["plan", "web"])

    # Then the command reports failure instead of crashing
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_plan_dry_run_plans_nothing(
    job_files: Callable[..., Path], monkeypatch, mocker, typer_runner
) -> None:
    """Verify --dry-run resolves targets without validating or planning any file."""
    # Given a job file and a mock binary
    job_files("web.hcl", "web")
    nomad = _patch_binary(monkeypatch, mocker)

    # When planning with --dry-run
    result = typer_runner.invoke(app, ["plan", "web", "--dry-run"])

    # Then it succeeds without touching the binary
    assert result.exit_code == 0
    nomad.validate.assert_not_called()
    nomad.plan.assert_not_called()
