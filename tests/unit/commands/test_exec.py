"""Tests for the nd exec command."""

from unittest.mock import MagicMock

from typer.testing import CliRunner

from nd.alloc_target import ResolvedTarget
from nd.cli import app
from nd.constants import DEFAULT_EXEC_SHELL, EXEC_SHELL_PROBE
from nd.jobspec import JobSpecError

runner = CliRunner()


def _patch(monkeypatch, *, target: ResolvedTarget | None, exit_code: int = 0) -> MagicMock:
    """Patch the resolver to return a fixed target and capture exec_shell calls."""
    from nd.commands import _common
    from nd.commands import exec as exec_module

    async def _fake_resolve(
        config, *, job_arg, task_arg, running_only=True
    ) -> tuple[int, ResolvedTarget | None]:
        return (exit_code, target)

    monkeypatch.setattr(_common, "resolve_target", _fake_resolve)
    shell = MagicMock(return_value=0)
    monkeypatch.setattr(exec_module.allocio, "exec_shell", shell)
    return shell


def test_exec_default_probes_bash_then_sh(monkeypatch):
    """Verify the default command probes for bash and falls back to sh."""
    # Given a resolver that returns a concrete target
    shell = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking exec with just a job name
    result = runner.invoke(app, ["exec", "web"])

    # Then exec_shell runs the bash-with-sh-fallback probe for the resolved alloc and task
    assert result.exit_code == 0
    assert shell.call_args.args[1:] == (
        "alloc-1",
        "server",
        [DEFAULT_EXEC_SHELL, "-c", EXEC_SHELL_PROBE],
    )


def test_exec_honors_shell_option(monkeypatch):
    """Verify --shell runs the chosen shell verbatim with no fallback."""
    # Given a resolver that returns a concrete target
    shell = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When requesting bash explicitly
    result = runner.invoke(app, ["exec", "web", "--shell", "/bin/bash"])

    # Then exec_shell is given exactly that shell as the whole command
    assert result.exit_code == 0
    assert shell.call_args.args[3] == ["/bin/bash"]


def test_exec_no_target_exits_with_resolver_code(monkeypatch):
    """Verify a resolver hard-failure exit code is propagated and nothing execs."""
    # Given a resolver that reports a selection failure
    shell = _patch(monkeypatch, target=None, exit_code=1)

    # When invoking exec
    result = runner.invoke(app, ["exec", "nope"])

    # Then the command exits 1 and never calls the binary layer
    assert result.exit_code == 1
    shell.assert_not_called()


def test_exec_missing_binary_exits_one(monkeypatch):
    """Verify a missing nomad binary surfaces a friendly error and exits 1."""
    # Given a resolver that returns a concrete target
    shell = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))
    # And exec_shell raises JobSpecError because the binary is absent
    shell.side_effect = JobSpecError("nomad not found")

    # When invoking exec
    result = runner.invoke(app, ["exec", "web"])

    # Then the command exits 1 without a raw traceback
    assert result.exit_code == 1
