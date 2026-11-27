"""Tests for the nd exec command."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from nd.binary import NomadBinaryError
from nd.cli import app
from nd.commands import _common
from nd.commands import exec as exec_mod
from nd.constants import DEFAULT_EXEC_SHELL, EXEC_SHELL_PROBE
from nd.targets import ResolvedTarget, SelectionError

if TYPE_CHECKING:
    from unittest.mock import MagicMock


def _patch_resolver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target: ResolvedTarget | None,
    error: SelectionError | None = None,
) -> dict[str, object]:
    """Patch the target resolver so tests exercise the command, not the picker.

    A given ``error`` is raised instead of returning ``target``, as a failed resolution does.

    Returns:
        dict[str, object]: The arguments of the resolver call, filled in when the command runs.
    """
    calls: dict[str, object] = {}

    async def _fake_resolve(
        config, *, job_arg, task_arg, running_only=True
    ) -> ResolvedTarget | None:
        calls.update(job_arg=job_arg, task_arg=task_arg, running_only=running_only)
        if error is not None:
            raise error
        return target

    monkeypatch.setattr(_common, "resolve_target", _fake_resolve)
    return calls


@pytest.fixture
def exec_command(fake_nomad_binary: MagicMock) -> MagicMock:
    """Make the stand-in binary's `exec_command` succeed with exit code 0.

    Returns:
        MagicMock: The `exec_command` mock, for call assertions.
    """
    fake_nomad_binary.exec_command.return_value = 0
    return fake_nomad_binary.exec_command


def test_exec_default_probes_bash_then_sh(monkeypatch, typer_runner, exec_command: MagicMock):
    """Verify the default command probes for bash and falls back to sh."""
    # Given a resolver that returns a concrete target
    _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )

    # When invoking exec with just a job name
    result = typer_runner.invoke(app, ["exec", "web"])

    # Then exec_command runs the bash-with-sh-fallback probe for the resolved alloc and task
    assert result.exit_code == 0
    assert exec_command.call_args.args == (
        "alloc-1",
        "server",
        [DEFAULT_EXEC_SHELL, "-c", EXEC_SHELL_PROBE],
    )


def test_exec_honors_shell_option(monkeypatch, typer_runner, exec_command: MagicMock):
    """Verify --shell runs the chosen shell verbatim with no fallback."""
    # Given a resolver that returns a concrete target
    _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )

    # When requesting bash explicitly
    result = typer_runner.invoke(app, ["exec", "web", "--shell", "/bin/bash"])

    # Then exec_command is given exactly that shell as the whole command
    assert result.exit_code == 0
    assert exec_command.call_args.args[2] == ["/bin/bash"]


def test_exec_unresolvable_target_exits_one(monkeypatch, typer_runner, exec_command: MagicMock):
    """Verify a selection failure ends the command with exit 1 and nothing execs."""
    # Given a resolver that reports a selection failure
    _patch_resolver(
        monkeypatch, target=None, error=SelectionError("No running job matching 'nope'")
    )

    # When invoking exec
    result = typer_runner.invoke(app, ["exec", "nope"])

    # Then the command exits 1 and never calls the binary layer
    assert result.exit_code == 1
    assert isinstance(result.exception, SelectionError)
    exec_command.assert_not_called()


def test_exec_missing_binary_exits_one(monkeypatch, typer_runner, exec_command: MagicMock):
    """Verify a missing nomad binary surfaces a friendly error and exits 1."""
    # Given a resolver that returns a concrete target
    _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )
    # And exec_command raises NomadBinaryError because the binary is absent
    exec_command.side_effect = NomadBinaryError("nomad not found")

    # When invoking exec
    result = typer_runner.invoke(app, ["exec", "web"])

    # Then the command exits 1 without a raw traceback
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)


@pytest.mark.parametrize(
    ("argv", "expected_command"),
    [
        pytest.param(["web", "--", "ps", "-ef"], ["ps", "-ef"], id="plain-command"),
        pytest.param(
            ["web", "--", "ls", "-la", "/alloc"], ["ls", "-la", "/alloc"], id="dashed-arguments"
        ),
        pytest.param(
            ["web", "--", "sh", "-c", "--", "x"],
            ["sh", "-c", "--", "x"],
            id="second-separator-belongs-to-command",
        ),
    ],
)
def test_exec_runs_command_after_separator(
    monkeypatch,
    typer_runner,
    exec_command: MagicMock,
    *,
    argv: list[str],
    expected_command: list[str],
):
    """Verify everything after the first `--` reaches the binary layer verbatim, unparsed."""
    # Given a resolver that returns a concrete target
    _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )

    # When passing a command after the separator
    result = typer_runner.invoke(app, ["exec", *argv])

    # Then the command runs as-is with no shell wrapping
    assert result.exit_code == 0
    assert exec_command.call_args.args == ("alloc-1", "server", expected_command)


def test_exec_command_keeps_job_argument_optional(
    monkeypatch, typer_runner, exec_command: MagicMock
):
    """Verify `nd exec -- ps` leaves JOB unset so the job picker still resolves it."""
    # Given a resolver that returns a concrete target
    calls = _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )

    # When passing a command with no job named
    result = typer_runner.invoke(app, ["exec", "--", "ps", "-ef"])

    # Then the resolver is asked to pick a job rather than matching "ps"
    assert result.exit_code == 0
    assert calls["job_arg"] is None
    assert exec_command.call_args.args[2] == ["ps", "-ef"]


def test_exec_option_still_follows_the_job_argument(
    monkeypatch, typer_runner, exec_command: MagicMock
):
    """Verify options are still accepted on either side of JOB in command mode."""
    # Given a resolver that returns a concrete target
    calls = _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )

    # When passing --task after the job and before the separator
    result = typer_runner.invoke(app, ["exec", "web", "-t", "server", "--", "cat", "/etc/hosts"])

    # Then both the option and the command are parsed
    assert result.exit_code == 0
    assert calls["task_arg"] == "server"
    assert exec_command.call_args.args[2] == ["cat", "/etc/hosts"]


def test_exec_rejects_shell_combined_with_a_command(
    monkeypatch, typer_runner, exec_command: MagicMock
):
    """Verify --shell and a `-- COMMAND` cannot be combined."""
    # Given a resolver that would return a concrete target
    _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )

    # When both are passed
    result = typer_runner.invoke(app, ["exec", "web", "-s", "/bin/bash", "--", "ps"])

    # Then it is a usage error naming the conflict, and nothing is executed
    assert result.exit_code == 2
    assert "--shell cannot be combined" in result.output
    exec_command.assert_not_called()


def test_exec_rejects_an_empty_command(monkeypatch, typer_runner, exec_command: MagicMock):
    """Verify a bare trailing `--` is a usage error rather than a silent exec_command."""
    # Given a resolver that would return a concrete target
    _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )

    # When the separator has nothing after it
    result = typer_runner.invoke(app, ["exec", "web", "--"])

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


def test_exec_command_exit_code_propagates(monkeypatch, typer_runner, exec_command: MagicMock):
    """Verify a non-zero exit code from the container command becomes nd's own exit code."""
    # Given a resolver that returns a concrete target, with the container command failing
    _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )
    exec_command.return_value = 3

    # When running a command that exits non-zero inside the container
    result = typer_runner.invoke(app, ["exec", "web", "--", "false"])

    # Then nd exits with that same code
    assert result.exit_code == 3


def test_exec_signal_death_maps_to_the_shell_convention(
    monkeypatch, typer_runner, exec_command: MagicMock
):
    """Verify a child killed by a signal exits 128 + signal rather than a truncated code."""
    # Given a resolver that returns a concrete target, with the child killed by SIGPIPE
    _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )
    exec_command.return_value = -13

    # When the exec output is closed early, as in `nd exec web -- yes | head -1`
    result = typer_runner.invoke(app, ["exec", "web", "--", "yes"])

    # Then nd reports 141, not the 243 that sys.exit(-13) would truncate to
    assert result.exit_code == 141


def test_exec_no_tty_flag_reaches_the_binary_layer(
    monkeypatch, typer_runner, exec_command: MagicMock
):
    """Verify -T is passed down as tty=False regardless of the session's streams."""
    # Given a resolver that returns a concrete target
    _patch_resolver(
        monkeypatch,
        target=ResolvedTarget("web", "alloc-1", "server", job_id="web", namespace="default"),
    )

    # When opening a shell with -T
    result = typer_runner.invoke(app, ["exec", "web", "-T"])

    # Then no pseudo-terminal is requested
    assert result.exit_code == 0
    assert exec_command.call_args.kwargs["tty"] is False
