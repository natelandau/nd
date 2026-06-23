"""Tests for the nomad binary wrappers."""

from __future__ import annotations

from pathlib import Path

import pytest

from nd import jobspec
from nd.jobspec import JobSpecError


class _FakeResult:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.ok = returncode == 0


def test_ensure_nomad_missing_raises(monkeypatch) -> None:
    """Verify a missing nomad binary raises JobSpecError."""
    monkeypatch.setattr(jobspec, "which", lambda name: None)
    with pytest.raises(JobSpecError, match="nomad"):
        jobspec.ensure_nomad()


def test_validate_passes(monkeypatch) -> None:
    """Verify validate runs `nomad job validate` and returns on success."""
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs) -> _FakeResult:
        calls.append(argv)
        return _FakeResult()

    monkeypatch.setattr(jobspec, "which", lambda name: Path("/usr/bin/nomad"))
    monkeypatch.setattr(jobspec, "run_command", fake_run)
    jobspec.validate(Path("/home/user/web.hcl"))
    assert calls == [["nomad", "job", "validate", "/home/user/web.hcl"]]


def test_compile_to_json_returns_stdout(monkeypatch) -> None:
    """Verify compile_to_json returns the binary's JSON stdout as bytes."""
    monkeypatch.setattr(jobspec, "which", lambda name: Path("/usr/bin/nomad"))
    monkeypatch.setattr(
        jobspec, "run_command", lambda argv, **kw: _FakeResult(stdout='{"Job": {"ID": "web"}}')
    )
    out = jobspec.compile_to_json(Path("/home/user/web.hcl"))
    assert out == b'{"Job": {"ID": "web"}}'


def test_compile_to_json_failure_raises(monkeypatch) -> None:
    """Verify a non-zero compile raises JobSpecError with stderr."""
    from nclutils.sh import ShellCommandFailedError

    def fake_run(argv, **kw) -> None:
        raise ShellCommandFailedError(msg="boom")

    monkeypatch.setattr(jobspec, "which", lambda name: Path("/usr/bin/nomad"))
    monkeypatch.setattr(jobspec, "run_command", fake_run)
    with pytest.raises(JobSpecError):
        jobspec.compile_to_json(Path("/home/user/web.hcl"))


def test_plan_returns_exit_code(monkeypatch) -> None:
    """Verify plan returns the binary's exit code and invokes `nomad job plan <file>`."""
    from nclutils.sh import ShellCommandError  # noqa: F401 (import used below for type context)

    recorded_argv: list[list[str]] = []
    recorded_kwargs: list[dict] = []

    def fake_run(argv, **kwargs) -> _FakeResult:
        # Given: record what was passed so assertions can inspect them
        recorded_argv.append(argv)
        recorded_kwargs.append(kwargs)
        return _FakeResult(returncode=1)

    # Given a nomad binary on PATH
    monkeypatch.setattr(jobspec, "which", lambda name: Path("/usr/bin/nomad"))
    monkeypatch.setattr(jobspec, "run_command", fake_run)

    # When plan is called
    result = jobspec.plan(Path("/home/user/web.hcl"))

    # Then the exit code is forwarded as-is
    assert result == 1
    # Then the correct argv was used
    assert recorded_argv == [["nomad", "job", "plan", "/home/user/web.hcl"]]
    # Then check=False and stream=True were passed so exit-1 is data, not a raised error
    assert recorded_kwargs[0]["check"] is False
    assert recorded_kwargs[0]["stream"] is True


def test_plan_launch_failure_raises(monkeypatch) -> None:
    """Verify a binary that cannot launch raises JobSpecError."""
    from nclutils.sh import ShellCommandError

    def fake_run(argv, **kwargs) -> None:
        # Given: the binary exists but fails to launch
        msg = "cannot launch"
        raise ShellCommandError(msg)

    # Given a nomad binary on PATH
    monkeypatch.setattr(jobspec, "which", lambda name: Path("/usr/bin/nomad"))
    monkeypatch.setattr(jobspec, "run_command", fake_run)

    # When / Then plan propagates the error as JobSpecError
    with pytest.raises(JobSpecError):
        jobspec.plan(Path("/home/user/web.hcl"))
