"""Tests for the nd exec command."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from nd.binary import NomadBinaryError
from nd.cli import app
from nd.commands import exec as exec_mod
from nd.constants import DEFAULT_EXEC_SHELL, EXEC_SHELL_PROBE
from nd.targets import ResolvedTarget

runner = CliRunner()
_RESOLVE_CALLS: dict[str, object] = {}


def _patch(monkeypatch, *, target: ResolvedTarget | None, exit_code: int = 0) -> MagicMock:
    """Patch the resolver and the NomadBinary factory; return the exec_command mock."""
    from nd.commands import _common

    _RESOLVE_CALLS.clear()

    async def _fake_resolve(
        config, *, job_arg, task_arg, running_only=True
    ) -> tuple[int, ResolvedTarget | None]:
        _RESOLVE_CALLS.update(job_arg=job_arg, task_arg=task_arg, running_only=running_only)
        return (exit_code, target)

    monkeypatch.setattr(_common, "resolve_target", _fake_resolve)
    nomad = MagicMock()
    nomad.exec_command.return_value = 0
    fake_cls = MagicMock()
    fake_cls.create.return_value = nomad
    monkeypatch.setattr(_common, "NomadBinary", fake_cls)
    return nomad.exec_command


def test_exec_default_probes_bash_then_sh(monkeypatch):
    """Verify the default command probes for bash and falls back to sh."""
    # Given a resolver that returns a concrete target
    shell = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When invoking exec with just a job name
    result = runner.invoke(app, ["exec", "web"])

    # Then exec_command runs the bash-with-sh-fallback probe for the resolved alloc and task
    assert result.exit_code == 0
    assert shell.call_args.args == (
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

    # Then exec_command is given exactly that shell as the whole command
    assert result.exit_code == 0
    assert shell.call_args.args[2] == ["/bin/bash"]


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
    # And exec_command raises NomadBinaryError because the binary is absent
    shell.side_effect = NomadBinaryError("nomad not found")

    # When invoking exec
    result = runner.invoke(app, ["exec", "web"])

    # Then the command exits 1 without a raw traceback
    assert result.exit_code == 1


def test_exec_runs_command_after_separator(monkeypatch):
    """Verify a command after `--` reaches the binary layer verbatim."""
    # Given a resolver that returns a concrete target
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When passing a command after the separator
    result = runner.invoke(app, ["exec", "web", "--", "ps", "-ef"])

    # Then the command runs as-is with no shell wrapping
    assert result.exit_code == 0
    assert exec_command.call_args.args == ("alloc-1", "server", ["ps", "-ef"])


def test_exec_command_keeps_job_argument_optional(monkeypatch):
    """Verify `nd exec -- ps` leaves JOB unset so the job picker still resolves it."""
    # Given a resolver that returns a concrete target
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When passing a command with no job named
    result = runner.invoke(app, ["exec", "--", "ps", "-ef"])

    # Then the resolver is asked to pick a job rather than matching "ps"
    assert result.exit_code == 0
    assert _RESOLVE_CALLS["job_arg"] is None
    assert exec_command.call_args.args[2] == ["ps", "-ef"]


def test_exec_command_preserves_dashed_arguments(monkeypatch):
    """Verify option-looking arguments after `--` reach the container untouched."""
    # Given a resolver that returns a concrete target
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When the command carries its own flags
    result = runner.invoke(app, ["exec", "web", "--", "ls", "-la", "/alloc"])

    # Then nd does not try to parse them
    assert result.exit_code == 0
    assert exec_command.call_args.args[2] == ["ls", "-la", "/alloc"]


def test_exec_command_splits_on_the_first_separator_only(monkeypatch):
    """Verify a second `--` belongs to the command rather than splitting again."""
    # Given a resolver that returns a concrete target
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When the command itself contains a separator
    result = runner.invoke(app, ["exec", "web", "--", "sh", "-c", "--", "x"])

    # Then only the first one is consumed
    assert result.exit_code == 0
    assert exec_command.call_args.args[2] == ["sh", "-c", "--", "x"]


def test_exec_option_still_follows_the_job_argument(monkeypatch):
    """Verify options are still accepted on either side of JOB in command mode."""
    # Given a resolver that returns a concrete target
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When passing --task after the job and before the separator
    result = runner.invoke(app, ["exec", "web", "-t", "server", "--", "cat", "/etc/hosts"])

    # Then both the option and the command are parsed
    assert result.exit_code == 0
    assert _RESOLVE_CALLS["task_arg"] == "server"
    assert exec_command.call_args.args[2] == ["cat", "/etc/hosts"]


def test_exec_rejects_shell_combined_with_a_command(monkeypatch, plain):
    """Verify --shell and a `-- COMMAND` cannot be combined."""
    # Given a resolver that would return a concrete target
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When both are passed
    result = runner.invoke(app, ["exec", "web", "-s", "/bin/bash", "--", "ps"])

    # Then it is a usage error naming the conflict, and nothing is executed
    assert result.exit_code == 2
    assert "--shell cannot be combined" in plain(result.output)
    exec_command.assert_not_called()


def test_exec_rejects_an_empty_command(monkeypatch):
    """Verify a bare trailing `--` is a usage error rather than a silent shell."""
    # Given a resolver that would return a concrete target
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When the separator has nothing after it
    result = runner.invoke(app, ["exec", "web", "--"])

    # Then it is a usage error and nothing is executed
    assert result.exit_code == 2
    exec_command.assert_not_called()


@pytest.mark.parametrize(
    ("no_tty", "stdin_tty", "stdout_tty", "expected"),
    [
        # Both streams must be terminals to request a pty.
        (False, True, True, True),
        # Stdin a tty but stdout redirected/piped: no pty, since nomad cannot attach
        # one to a non-terminal stream. This is the case that changed behavior for
        # shell mode (it used to ignore stdout).
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, False),
        # -T always wins regardless of the streams.
        (True, True, True, False),
    ],
)
def test_wants_tty_policy(monkeypatch, no_tty, stdin_tty, stdout_tty, expected):
    """Verify the pseudo-terminal decision across stream and -T combinations."""
    # Given a session whose streams are terminals or not
    monkeypatch.setattr(exec_mod.sys, "stdin", SimpleNamespace(isatty=lambda: stdin_tty))
    monkeypatch.setattr(exec_mod.sys, "stdout", SimpleNamespace(isatty=lambda: stdout_tty))

    # When deciding whether to request a terminal, Then the policy holds
    assert exec_mod._wants_tty(no_tty=no_tty) is expected


def test_exec_command_exit_code_propagates(monkeypatch):
    """Verify a non-zero exit code from the container command becomes nd's own exit code."""
    # Given a resolver that returns a concrete target, with the container command failing
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))
    exec_command.return_value = 3

    # When running a command that exits non-zero inside the container
    result = runner.invoke(app, ["exec", "web", "--", "false"])

    # Then nd exits with that same code
    assert result.exit_code == 3


def test_exec_signal_death_maps_to_the_shell_convention(monkeypatch):
    """Verify a child killed by a signal exits 128 + signal rather than a truncated code."""
    # Given a resolver that returns a concrete target, with the child killed by SIGPIPE
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))
    exec_command.return_value = -13

    # When the exec output is closed early, as in `nd exec web -- yes | head -1`
    result = runner.invoke(app, ["exec", "web", "--", "yes"])

    # Then nd reports 141, not the 243 that sys.exit(-13) would truncate to
    assert result.exit_code == 141


def test_exec_no_tty_flag_reaches_the_binary_layer(monkeypatch):
    """Verify -T is passed down as tty=False regardless of the session's streams."""
    # Given a resolver that returns a concrete target
    exec_command = _patch(monkeypatch, target=ResolvedTarget("web", "alloc-1", "server"))

    # When opening a shell with -T
    result = runner.invoke(app, ["exec", "web", "-T"])

    # Then no pseudo-terminal is requested
    assert result.exit_code == 0
    assert exec_command.call_args.kwargs["tty"] is False
