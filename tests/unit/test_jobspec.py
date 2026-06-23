"""Tests for the nomad binary wrappers."""

from __future__ import annotations

from pathlib import Path

import pytest

from nd.binary import NomadBinaryError, env, jobspec
from nd.nomad.config import NomadConfig


@pytest.fixture
def nomad_config() -> NomadConfig:
    """Provide a non-default config so env forwarding is observable."""
    return NomadConfig(address="http://nomad.test:4646", token="t")  # noqa: S106


class _FakeResult:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.ok = returncode == 0


def test_ensure_nomad_missing_raises(monkeypatch) -> None:
    """Verify a missing nomad binary raises NomadBinaryError."""
    monkeypatch.setattr(env, "which", lambda name: None)
    with pytest.raises(NomadBinaryError, match="nomad"):
        env.ensure_nomad()


def test_binary_env_overlays_config_onto_environment(monkeypatch, nomad_config) -> None:
    """Verify binary_env overlays the resolved config onto the ambient environment."""
    # Given an ambient environment with a sentinel variable
    monkeypatch.setenv("SENTINEL_VAR", "keep-me")

    # When building the binary environment
    result = env.binary_env(nomad_config)

    # Then the config targets the cluster and the ambient variables are preserved
    assert result["NOMAD_ADDR"] == "http://nomad.test:4646"
    assert result["NOMAD_TOKEN"] == "t"  # noqa: S105
    assert result["SENTINEL_VAR"] == "keep-me"


def test_validate_passes(monkeypatch, nomad_config) -> None:
    """Verify validate runs `nomad job validate` and forwards the config env."""
    calls: list[tuple[list[str], dict]] = []

    def fake_run(argv, **kwargs) -> _FakeResult:
        calls.append((argv, kwargs))
        return _FakeResult()

    monkeypatch.setattr(jobspec, "run_command", fake_run)

    # When validating a job file with a resolved binary path
    jobspec.validate(Path("/home/user/web.hcl"), nomad_config, nomad_bin=Path("/usr/bin/nomad"))

    # Then the correct argv runs with the config's cluster address in the env
    argv, kwargs = calls[0]
    assert argv == ["/usr/bin/nomad", "job", "validate", "/home/user/web.hcl"]
    assert kwargs["env"]["NOMAD_ADDR"] == "http://nomad.test:4646"


def test_compile_to_json_returns_stdout(monkeypatch, nomad_config) -> None:
    """Verify compile_to_json returns the binary's JSON stdout as bytes."""
    monkeypatch.setattr(
        jobspec, "run_command", lambda argv, **kw: _FakeResult(stdout='{"Job": {"ID": "web"}}')
    )
    out = jobspec.compile_to_json(
        Path("/home/user/web.hcl"), nomad_config, nomad_bin=Path("/usr/bin/nomad")
    )
    assert out == b'{"Job": {"ID": "web"}}'


def test_compile_to_json_forwards_config_env(monkeypatch, nomad_config) -> None:
    """Verify compile_to_json hands the resolved config env to the binary."""
    calls: list[dict] = []

    def fake_run(argv, **kwargs) -> _FakeResult:
        calls.append(kwargs)
        return _FakeResult(stdout="{}")

    monkeypatch.setattr(jobspec, "run_command", fake_run)

    # When compiling a job file with a resolved binary path
    jobspec.compile_to_json(
        Path("/home/user/web.hcl"), nomad_config, nomad_bin=Path("/usr/bin/nomad")
    )

    # Then the config's cluster address rides along in the env
    assert calls[0]["env"]["NOMAD_ADDR"] == "http://nomad.test:4646"


def test_compile_to_json_failure_raises(monkeypatch, nomad_config) -> None:
    """Verify a non-zero compile raises NomadBinaryError with stderr."""
    from nclutils.sh import ShellCommandFailedError

    def fake_run(argv, **kw) -> None:
        raise ShellCommandFailedError(msg="boom")

    monkeypatch.setattr(jobspec, "run_command", fake_run)
    with pytest.raises(NomadBinaryError):
        jobspec.compile_to_json(
            Path("/home/user/web.hcl"), nomad_config, nomad_bin=Path("/usr/bin/nomad")
        )


def test_plan_returns_exit_code(monkeypatch, nomad_config) -> None:
    """Verify plan returns the binary's exit code and invokes `nomad job plan <file>`."""
    recorded_argv: list[list[str]] = []
    recorded_kwargs: list[dict] = []

    def fake_run(argv, **kwargs) -> _FakeResult:
        # Given: record what was passed so assertions can inspect them
        recorded_argv.append(argv)
        recorded_kwargs.append(kwargs)
        return _FakeResult(returncode=1)

    monkeypatch.setattr(jobspec, "run_command", fake_run)

    # When plan is called with a resolved binary path
    result = jobspec.plan(
        Path("/home/user/web.hcl"), nomad_config, nomad_bin=Path("/usr/bin/nomad")
    )

    # Then the exit code is forwarded as-is
    assert result == 1
    # Then the correct argv was used
    assert recorded_argv == [["/usr/bin/nomad", "job", "plan", "/home/user/web.hcl"]]
    # Then check=False and stream=True were passed so exit-1 is data, not a raised error
    assert recorded_kwargs[0]["check"] is False
    assert recorded_kwargs[0]["stream"] is True
    # Then the config's cluster address rode along in the env
    assert recorded_kwargs[0]["env"]["NOMAD_ADDR"] == "http://nomad.test:4646"


def test_plan_launch_failure_raises(monkeypatch, nomad_config) -> None:
    """Verify a binary that cannot launch raises NomadBinaryError."""
    from nclutils.sh import ShellCommandError

    def fake_run(argv, **kwargs) -> None:
        # Given: the binary exists but fails to launch
        msg = "cannot launch"
        raise ShellCommandError(msg)

    monkeypatch.setattr(jobspec, "run_command", fake_run)

    # When / Then plan propagates the error as NomadBinaryError
    with pytest.raises(NomadBinaryError):
        jobspec.plan(Path("/home/user/web.hcl"), nomad_config, nomad_bin=Path("/usr/bin/nomad"))
