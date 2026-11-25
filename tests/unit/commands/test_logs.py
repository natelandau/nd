"""Tests for the nd logs command."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nd.binary import NomadBinaryError
from nd.cli import app
from nd.targets import ResolvedTarget


def _patch(monkeypatch, *, target: ResolvedTarget | None, exit_code: int = 0) -> MagicMock:
    """Patch the resolver and the NomadBinary factory; return the stream_logs mock."""
    from nd.commands import _common

    async def _fake_resolve(
        config, *, job_arg, task_arg, running_only=True
    ) -> tuple[int, ResolvedTarget | None]:
        return (exit_code, target)

    monkeypatch.setattr(_common, "resolve_target", _fake_resolve)
    nomad = MagicMock()
    nomad.stream_logs.return_value = 0
    fake_cls = MagicMock()
    fake_cls.create.return_value = nomad
    monkeypatch.setattr(_common, "NomadBinary", fake_cls)
    return nomad.stream_logs


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
    monkeypatch, typer_runner, *, argv: list[str], expected_kwargs: dict[str, object]
):
    """Verify the stream selection and --tail reach stream_logs, defaulting to both streams."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking logs with the parametrized options
    result = typer_runner.invoke(app, ["logs", "web", *argv])

    # Then the options reach stream_logs
    assert result.exit_code == 0
    for name, expected in expected_kwargs.items():
        assert stream.call_args.kwargs[name] == expected


def test_logs_no_target_exits_with_resolver_code(monkeypatch, typer_runner):
    """Verify a resolver hard-failure exit code is propagated and nothing streams."""
    # Given a resolver that reports a selection failure
    stream = _patch(monkeypatch, target=None, exit_code=1)

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "nope"])

    # Then the command exits 1 and never calls the binary layer
    assert result.exit_code == 1
    stream.assert_not_called()


def test_logs_missing_binary_exits_one(monkeypatch, typer_runner):
    """Verify a missing nomad binary surfaces a friendly error and exits 1."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))
    # And stream_logs raises NomadBinaryError because the binary is absent
    stream.side_effect = NomadBinaryError("nomad not found")

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then the command exits 1 without a raw traceback
    assert result.exit_code == 1


def test_logs_forwards_export_path(monkeypatch, typer_runner):
    """Verify --export is forwarded as a Path to stream_logs."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking logs with an export path
    result = typer_runner.invoke(app, ["logs", "web", "--export", "/var/log/out.log"])

    # Then stream_logs receives export_path as a Path object
    assert result.exit_code == 0
    assert stream.call_args.kwargs["export_path"] == Path("/var/log/out.log")


def test_logs_propagates_nonzero_exit_code(monkeypatch, typer_runner):
    """Verify a non-zero exit code from stream_logs is propagated to the shell."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))
    # And stream_logs returns a failure code
    stream.return_value = 3

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then the command exits with that same code
    assert result.exit_code == 3


def test_logs_resolves_including_dead_targets(monkeypatch, typer_runner):
    """Verify logs resolves with running_only=False so dead tasks stay reachable."""
    # Given a resolver that records the running_only flag it is asked for
    from nd.commands import _common

    captured: dict[str, bool] = {}

    async def _fake_resolve(
        config, *, job_arg, task_arg, running_only=True
    ) -> tuple[int, ResolvedTarget | None]:
        captured["running_only"] = running_only
        return (0, ResolvedTarget("web", "alloc-1", "server"))

    monkeypatch.setattr(_common, "resolve_target", _fake_resolve)
    nomad = MagicMock()
    nomad.stream_logs.return_value = 0
    fake_cls = MagicMock()
    fake_cls.create.return_value = nomad
    monkeypatch.setattr(_common, "NomadBinary", fake_cls)

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then the resolver is asked to include non-running (dead) targets
    assert result.exit_code == 0
    assert captured["running_only"] is False
