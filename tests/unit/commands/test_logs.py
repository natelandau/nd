"""Tests for the nd logs command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from nd.binary import NomadBinaryError
from nd.cli import app
from nd.commands import _common
from nd.targets import ResolvedTarget

if TYPE_CHECKING:
    from unittest.mock import MagicMock


def _patch_resolver(
    monkeypatch: pytest.MonkeyPatch, *, target: ResolvedTarget | None, exit_code: int = 0
) -> dict[str, object]:
    """Patch the target resolver so tests exercise the command, not the picker.

    Returns:
        dict[str, object]: The arguments of the resolver call, filled in when the command runs.
    """
    calls: dict[str, object] = {}

    async def _fake_resolve(
        config, *, job_arg, task_arg, running_only=True
    ) -> tuple[int, ResolvedTarget | None]:
        calls.update(job_arg=job_arg, task_arg=task_arg, running_only=running_only)
        return (exit_code, target)

    monkeypatch.setattr(_common, "resolve_target", _fake_resolve)
    return calls


@pytest.fixture
def stream_logs(fake_nomad_binary: MagicMock) -> MagicMock:
    """Make the stand-in binary's `stream_logs` succeed with exit code 0.

    Returns:
        MagicMock: The `stream_logs` mock, for call assertions.
    """
    fake_nomad_binary.stream_logs.return_value = 0
    return fake_nomad_binary.stream_logs


@pytest.mark.parametrize(
    ("argv", "expected_kwargs"),
    [
        pytest.param(
            [],
            {"streams": ("stdout", "stderr"), "tail": None, "export_path": None},
            id="default-both-streams",
        ),
        pytest.param(
            ["--stderr", "--tail", "50"], {"streams": ("stderr",), "tail": 50}, id="stderr-tail"
        ),
        pytest.param(["--stdout"], {"streams": ("stdout",)}, id="stdout-only"),
    ],
)
def test_logs_forwards_stream_options(
    monkeypatch,
    typer_runner,
    stream_logs: MagicMock,
    *,
    argv: list[str],
    expected_kwargs: dict[str, object],
):
    """Verify the stream selection and --tail reach stream_logs, defaulting to both streams."""
    # Given a resolver that returns a concrete target
    _patch_resolver(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking logs with the parametrized options
    result = typer_runner.invoke(app, ["logs", "web", *argv])

    # Then the options reach stream_logs
    assert result.exit_code == 0
    for name, expected in expected_kwargs.items():
        assert stream_logs.call_args.kwargs[name] == expected


def test_logs_no_target_exits_with_resolver_code(monkeypatch, typer_runner, stream_logs: MagicMock):
    """Verify a resolver hard-failure exit code is propagated and nothing streams."""
    # Given a resolver that reports a selection failure
    _patch_resolver(monkeypatch, target=None, exit_code=1)

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "nope"])

    # Then the command exits 1 and never calls the binary layer
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    stream_logs.assert_not_called()


def test_logs_missing_binary_exits_one(monkeypatch, typer_runner, stream_logs: MagicMock):
    """Verify a missing nomad binary surfaces a friendly error and exits 1."""
    # Given a resolver that returns a concrete target
    _patch_resolver(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))
    # And stream_logs raises NomadBinaryError because the binary is absent
    stream_logs.side_effect = NomadBinaryError("nomad not found")

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then the command exits 1 without a raw traceback
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)


def test_logs_forwards_export_path(monkeypatch, typer_runner, stream_logs: MagicMock):
    """Verify --export is forwarded as a Path to stream_logs."""
    # Given a resolver that returns a concrete target
    _patch_resolver(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking logs with an export path
    result = typer_runner.invoke(app, ["logs", "web", "--export", "/var/log/out.log"])

    # Then stream_logs receives export_path as a Path object
    assert result.exit_code == 0
    assert stream_logs.call_args.kwargs["export_path"] == Path("/var/log/out.log")


def test_logs_propagates_nonzero_exit_code(monkeypatch, typer_runner, stream_logs: MagicMock):
    """Verify a non-zero exit code from stream_logs is propagated to the shell."""
    # Given a resolver that returns a concrete target
    _patch_resolver(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))
    # And stream_logs returns a failure code
    stream_logs.return_value = 3

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then the command exits with that same code
    assert result.exit_code == 3


@pytest.mark.usefixtures("stream_logs")
def test_logs_resolves_including_dead_targets(monkeypatch, typer_runner):
    """Verify logs resolves with running_only=False so dead tasks stay reachable."""
    # Given a resolver that records the running_only flag it is asked for
    calls = _patch_resolver(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then the resolver is asked to include non-running (dead) targets
    assert result.exit_code == 0
    assert calls["running_only"] is False
