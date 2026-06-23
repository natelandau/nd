"""Tests for NomadBinary, the configured handle to the local nomad binary."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nd.binary import NomadBinary, NomadBinaryError
from nd.binary import runner as runner_mod
from nd.nomad.config import NomadConfig


@pytest.fixture
def nomad() -> NomadBinary:
    """A NomadBinary bound to a non-default config and a fixed binary path."""
    config = NomadConfig(address="http://nomad.test:4646", token="t")  # noqa: S106
    return NomadBinary(config, Path("/usr/bin/nomad"))


class _FakeResult:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.ok = returncode == 0


# --- job specs (HCL2 compile/validate) -----------------------------------------------


def test_validate_passes(monkeypatch, nomad) -> None:
    """Verify validate runs `nomad job validate` and forwards the config env."""
    # Given a captured run_command
    calls: list[tuple[list[str], dict]] = []

    def fake_run(argv, **kwargs) -> _FakeResult:
        calls.append((argv, kwargs))
        return _FakeResult()

    monkeypatch.setattr(runner_mod, "run_command", fake_run)

    # When validating a job file
    nomad.validate(Path("/home/user/web.hcl"))

    # Then the argv uses the resolved binary path and carries the config's cluster env
    argv, kwargs = calls[0]
    assert argv == ["/usr/bin/nomad", "job", "validate", "/home/user/web.hcl"]
    assert kwargs["env"]["NOMAD_ADDR"] == "http://nomad.test:4646"


def test_compile_to_json_returns_stdout(monkeypatch, nomad) -> None:
    """Verify compile_to_json returns the binary's JSON stdout as bytes."""
    # Given a binary that emits a compiled job
    monkeypatch.setattr(
        runner_mod, "run_command", lambda argv, **kw: _FakeResult(stdout='{"Job": {"ID": "web"}}')
    )

    # When compiling a job file
    out = nomad.compile_to_json(Path("/home/user/web.hcl"))

    # Then the stdout is returned as bytes
    assert out == b'{"Job": {"ID": "web"}}'


def test_compile_to_json_forwards_config_env(monkeypatch, nomad) -> None:
    """Verify compile_to_json hands the resolved config env to the binary."""
    # Given a captured run_command
    calls: list[dict] = []

    def fake_run(argv, **kwargs) -> _FakeResult:
        calls.append(kwargs)
        return _FakeResult(stdout="{}")

    monkeypatch.setattr(runner_mod, "run_command", fake_run)

    # When compiling a job file
    nomad.compile_to_json(Path("/home/user/web.hcl"))

    # Then the config's cluster address rides along in the env
    assert calls[0]["env"]["NOMAD_ADDR"] == "http://nomad.test:4646"


def test_compile_to_json_failure_raises(monkeypatch, nomad) -> None:
    """Verify a non-zero compile raises NomadBinaryError with stderr."""
    from nclutils.sh import ShellCommandFailedError

    # Given a binary that fails
    def fake_run(argv, **kw) -> None:
        raise ShellCommandFailedError(msg="boom")

    monkeypatch.setattr(runner_mod, "run_command", fake_run)

    # When / Then compiling raises the friendly error
    with pytest.raises(NomadBinaryError):
        nomad.compile_to_json(Path("/home/user/web.hcl"))


def test_plan_returns_exit_code(monkeypatch, nomad) -> None:
    """Verify plan returns the binary's exit code and invokes `nomad job plan <file>`."""
    # Given a captured run_command that reports changes (exit 1)
    recorded_argv: list[list[str]] = []
    recorded_kwargs: list[dict] = []

    def fake_run(argv, **kwargs) -> _FakeResult:
        recorded_argv.append(argv)
        recorded_kwargs.append(kwargs)
        return _FakeResult(returncode=1)

    monkeypatch.setattr(runner_mod, "run_command", fake_run)

    # When planning a job file
    result = nomad.plan(Path("/home/user/web.hcl"))

    # Then the exit code is forwarded and the binary ran streamed, non-raising
    assert result == 1
    assert recorded_argv == [["/usr/bin/nomad", "job", "plan", "/home/user/web.hcl"]]
    assert recorded_kwargs[0]["check"] is False
    assert recorded_kwargs[0]["stream"] is True
    assert recorded_kwargs[0]["env"]["NOMAD_ADDR"] == "http://nomad.test:4646"


def test_plan_launch_failure_raises(monkeypatch, nomad) -> None:
    """Verify a binary that cannot launch raises NomadBinaryError."""
    from nclutils.sh import ShellCommandError

    # Given a binary that cannot launch
    def fake_run(argv, **kwargs) -> None:
        msg = "cannot launch"
        raise ShellCommandError(msg)

    monkeypatch.setattr(runner_mod, "run_command", fake_run)

    # When / Then plan propagates the error as NomadBinaryError
    with pytest.raises(NomadBinaryError):
        nomad.plan(Path("/home/user/web.hcl"))


# --- allocations (interactive exec, log streaming) -----------------------------------


def _patch_subprocess(
    monkeypatch, *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0
) -> MagicMock:
    """Patch subprocess.run on the runner module; return the run mock for argv assertions."""
    run = MagicMock(return_value=MagicMock(returncode=returncode, stdout=stdout, stderr=stderr))
    monkeypatch.setattr(runner_mod.subprocess, "run", run)
    return run


def test_exec_shell_allocates_tty_when_interactive(monkeypatch, nomad) -> None:
    """Verify exec_shell requests a pseudo-tty (-t) when stdin is a terminal."""
    # Given a patched subprocess and an interactive stdin
    run = _patch_subprocess(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    # When opening a shell in a task
    code = nomad.exec_shell("alloc-1", "web", ["/bin/bash"])

    # Then the argv targets the task interactively (-i -t) and the exit code is returned
    argv = run.call_args.args[0]
    assert argv == [
        "/usr/bin/nomad",
        "alloc",
        "exec",
        "-task",
        "web",
        "-i",
        "-t",
        "alloc-1",
        "/bin/bash",
    ]
    assert run.call_args.kwargs["env"]["NOMAD_ADDR"] == "http://nomad.test:4646"
    assert code == 0


def test_exec_shell_omits_tty_when_not_a_terminal(monkeypatch, nomad) -> None:
    """Verify exec_shell omits -t when stdin is not a terminal (CI, pipe)."""
    # Given a patched subprocess and a non-terminal stdin
    run = _patch_subprocess(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    # When opening a shell in a task
    nomad.exec_shell("alloc-1", "web", ["/bin/bash"])

    # Then the argv passes -i but never forces a pseudo-tty against the pipe
    argv = run.call_args.args[0]
    assert argv == ["/usr/bin/nomad", "alloc", "exec", "-task", "web", "-i", "alloc-1", "/bin/bash"]
    assert "-t" not in argv


def test_exec_shell_appends_multi_arg_command(monkeypatch, nomad) -> None:
    """Verify a multi-element command (the bash-fallback probe) is splatted into argv."""
    # Given a patched subprocess and an interactive stdin
    run = _patch_subprocess(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    # When opening a shell with a `sh -c` probe command
    nomad.exec_shell("alloc-1", "web", ["/bin/sh", "-c", "exec bash || exec sh"])

    # Then every command element trails the alloc id in order
    argv = run.call_args.args[0]
    assert argv[-4:] == ["alloc-1", "/bin/sh", "-c", "exec bash || exec sh"]


def test_stream_logs_default_follows_both_streams(monkeypatch, nomad) -> None:
    """Verify the default mode follows both streams via Nomad's native interleaving."""
    # Given a patched subprocess
    run = _patch_subprocess(monkeypatch)

    # When streaming logs with no stream selection, tail, or export
    nomad.stream_logs("alloc-1", "web")

    # Then it follows with no stream flag so the binary merges stdout and stderr
    argv = run.call_args.args[0]
    assert argv == ["/usr/bin/nomad", "alloc", "logs", "-f", "-task", "web", "alloc-1"]


def test_stream_logs_follow_single_stream_is_explicit(monkeypatch, nomad) -> None:
    """Verify selecting one stream passes its explicit flag in follow mode."""
    # Given a patched subprocess
    run = _patch_subprocess(monkeypatch)

    # When following only stdout
    nomad.stream_logs("alloc-1", "web", streams=("stdout",))

    # Then -stdout is passed explicitly alongside -f
    argv = run.call_args.args[0]
    assert argv == ["/usr/bin/nomad", "alloc", "logs", "-f", "-stdout", "-task", "web", "alloc-1"]


def test_stream_logs_stderr_tail_is_static(monkeypatch, nomad) -> None:
    """Verify a single stream with a tail count produces a static read (no -f)."""
    # Given a patched subprocess
    run = _patch_subprocess(monkeypatch)

    # When tailing the last 50 stderr lines
    nomad.stream_logs("alloc-1", "web", streams=("stderr",), tail=50)

    # Then it reads the tail of stderr without following
    argv = run.call_args.args[0]
    assert argv == [
        "/usr/bin/nomad",
        "alloc",
        "logs",
        "-tail",
        "-n",
        "50",
        "-stderr",
        "-task",
        "web",
        "alloc-1",
    ]


def test_stream_logs_export_writes_snapshot(monkeypatch, tmp_path, nomad) -> None:
    """Verify export captures a single stream and writes it to the file without following."""
    # Given a binary that returns log bytes
    run = _patch_subprocess(monkeypatch, stdout=b"line1\nline2\n")
    out = tmp_path / "web.log"

    # When exporting only stdout
    code = nomad.stream_logs("alloc-1", "web", streams=("stdout",), export_path=out)

    # Then it captured output (no -f), wrote the file, and reported success
    argv = run.call_args.args[0]
    assert "-f" not in argv
    assert run.call_args.kwargs["capture_output"] is True
    assert out.read_bytes() == b"line1\nline2\n"
    assert code == 0


def test_stream_logs_export_both_concatenates_streams(monkeypatch, tmp_path, nomad) -> None:
    """Verify exporting both streams reads each in turn and concatenates them."""
    # Given a binary that returns log bytes for every read
    run = _patch_subprocess(monkeypatch, stdout=b"chunk\n")
    out = tmp_path / "web.log"

    # When exporting with the default (both) stream selection
    nomad.stream_logs("alloc-1", "web", export_path=out)

    # Then both stdout and stderr are read (two calls) and their output is concatenated
    assert run.call_count == 2
    assert out.read_bytes() == b"chunk\nchunk\n"


def test_stream_logs_export_failure_raises(monkeypatch, tmp_path, nomad) -> None:
    """Verify export raises NomadBinaryError when the binary exits non-zero."""
    # Given a binary that fails with stderr
    _patch_subprocess(monkeypatch, returncode=1, stderr=b"boom")
    out = tmp_path / "web.log"

    # When / Then exporting raises and the file is not written
    with pytest.raises(NomadBinaryError):
        nomad.stream_logs("alloc-1", "web", streams=("stdout",), export_path=out)
    assert not out.exists()


def test_stream_logs_export_with_tail_writes_snapshot(monkeypatch, tmp_path, nomad) -> None:
    """Verify combined tail and export captures last N lines to file without following."""
    # Given a binary that returns log bytes
    run = _patch_subprocess(monkeypatch, stdout=b"x\n")
    out = tmp_path / "t.log"

    # When exporting only stdout with a tail count
    nomad.stream_logs("alloc-1", "web", streams=("stdout",), tail=10, export_path=out)

    # Then it includes tail args, does not follow, and writes the file
    argv = run.call_args.args[0]
    assert "-tail" in argv
    assert "-n" in argv
    assert "10" in argv
    assert "-f" not in argv
    assert out.read_bytes() == b"x\n"
