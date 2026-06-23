"""Tests for the nd logs command."""

from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from nd.alloc_target import ResolvedTarget
from nd.cli import app
from nd.jobspec import JobSpecError

runner = CliRunner()


def _patch(monkeypatch, *, target: ResolvedTarget | None, exit_code: int = 0) -> MagicMock:
    """Patch the resolver to return a fixed target and capture stream_logs calls."""
    from nd.commands import _common
    from nd.commands import logs as logs_module

    async def _fake_resolve(
        config, *, job_arg, task_arg, running_only=True
    ) -> tuple[int, ResolvedTarget | None]:
        return (exit_code, target)

    monkeypatch.setattr(_common, "resolve_target", _fake_resolve)
    stream = MagicMock(return_value=0)
    monkeypatch.setattr(logs_module.allocio, "stream_logs", stream)
    return stream


def test_logs_passes_default_both_follow(monkeypatch):
    """Verify a resolved target streams both stdout and stderr with no tail or export."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking logs with just a job name
    result = runner.invoke(app, ["logs", "web"])

    # Then stream_logs is called for both streams and the command succeeds
    assert result.exit_code == 0
    assert stream.call_args.kwargs["streams"] == ("stdout", "stderr")
    assert stream.call_args.kwargs["tail"] is None
    assert stream.call_args.kwargs["export_path"] is None


def test_logs_forwards_stderr_and_tail(monkeypatch):
    """Verify --stderr isolates the stderr stream and --tail is forwarded."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When tailing 50 stderr lines
    result = runner.invoke(app, ["logs", "web", "--stderr", "--tail", "50"])

    # Then the flags reach stream_logs
    assert result.exit_code == 0
    assert stream.call_args.kwargs["streams"] == ("stderr",)
    assert stream.call_args.kwargs["tail"] == 50


def test_logs_stdout_flag_isolates_stdout(monkeypatch):
    """Verify --stdout limits the read to the stdout stream only."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking logs with --stdout
    result = runner.invoke(app, ["logs", "web", "--stdout"])

    # Then stream_logs reads only stdout
    assert result.exit_code == 0
    assert stream.call_args.kwargs["streams"] == ("stdout",)


def test_logs_no_target_exits_with_resolver_code(monkeypatch):
    """Verify a resolver hard-failure exit code is propagated and nothing streams."""
    # Given a resolver that reports a selection failure
    stream = _patch(monkeypatch, target=None, exit_code=1)

    # When invoking logs
    result = runner.invoke(app, ["logs", "nope"])

    # Then the command exits 1 and never calls the binary layer
    assert result.exit_code == 1
    stream.assert_not_called()


def test_logs_missing_binary_exits_one(monkeypatch):
    """Verify a missing nomad binary surfaces a friendly error and exits 1."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))
    # And stream_logs raises JobSpecError because the binary is absent
    stream.side_effect = JobSpecError("nomad not found")

    # When invoking logs
    result = runner.invoke(app, ["logs", "web"])

    # Then the command exits 1 without a raw traceback
    assert result.exit_code == 1


def test_logs_forwards_export_path(monkeypatch):
    """Verify --export is forwarded as a Path to stream_logs."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking logs with an export path
    result = runner.invoke(app, ["logs", "web", "--export", "/var/log/out.log"])

    # Then stream_logs receives export_path as a Path object
    assert result.exit_code == 0
    assert stream.call_args.kwargs["export_path"] == Path("/var/log/out.log")


def test_logs_propagates_nonzero_exit_code(monkeypatch):
    """Verify a non-zero exit code from stream_logs is propagated to the shell."""
    # Given a resolver that returns a concrete target
    stream = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))
    # And stream_logs returns a failure code
    stream.return_value = 3

    # When invoking logs
    result = runner.invoke(app, ["logs", "web"])

    # Then the command exits with that same code
    assert result.exit_code == 3


def test_logs_resolves_including_dead_targets(monkeypatch):
    """Verify logs resolves with running_only=False so dead tasks stay reachable."""
    # Given a resolver that records the running_only flag it is asked for
    from nd.commands import _common
    from nd.commands import logs as logs_module

    captured: dict[str, bool] = {}

    async def _fake_resolve(
        config, *, job_arg, task_arg, running_only=True
    ) -> tuple[int, ResolvedTarget | None]:
        captured["running_only"] = running_only
        return (0, ResolvedTarget("web", "alloc-1", "server"))

    monkeypatch.setattr(_common, "resolve_target", _fake_resolve)
    monkeypatch.setattr(logs_module.allocio, "stream_logs", MagicMock(return_value=0))

    # When invoking logs
    result = runner.invoke(app, ["logs", "web"])

    # Then the resolver is asked to include non-running (dead) targets
    assert result.exit_code == 0
    assert captured["running_only"] is False
