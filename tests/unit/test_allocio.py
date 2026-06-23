"""Tests for the nomad alloc binary wrappers."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nd.binary import NomadBinaryError, allocio
from nd.nomad.config import NomadConfig


@pytest.fixture
def _config() -> NomadConfig:
    return NomadConfig(address="http://nomad.test:4646", token="t")  # noqa: S106


def _patch_binary(
    monkeypatch, *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0
) -> MagicMock:
    """Patch ensure_nomad and subprocess.run; return the run mock for argv assertions."""
    monkeypatch.setattr(allocio, "ensure_nomad", lambda: Path("/usr/bin/nomad"))
    run = MagicMock(return_value=MagicMock(returncode=returncode, stdout=stdout, stderr=stderr))
    monkeypatch.setattr(allocio.subprocess, "run", run)
    return run


def test_exec_shell_allocates_tty_when_interactive(monkeypatch, _config):  # noqa: PT019
    """Verify exec_shell requests a pseudo-tty (-t) when stdin is a terminal."""
    # Given a patched nomad binary and an interactive stdin
    run = _patch_binary(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    # When opening a shell in a task
    code = allocio.exec_shell(_config, "alloc-1", "web", ["/bin/bash"])

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


def test_exec_shell_omits_tty_when_not_a_terminal(monkeypatch, _config):  # noqa: PT019
    """Verify exec_shell omits -t when stdin is not a terminal (CI, pipe)."""
    # Given a patched nomad binary and a non-terminal stdin
    run = _patch_binary(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    # When opening a shell in a task
    allocio.exec_shell(_config, "alloc-1", "web", ["/bin/bash"])

    # Then the argv passes -i but never forces a pseudo-tty against the pipe
    argv = run.call_args.args[0]
    assert argv == [
        "/usr/bin/nomad",
        "alloc",
        "exec",
        "-task",
        "web",
        "-i",
        "alloc-1",
        "/bin/bash",
    ]
    assert "-t" not in argv


def test_exec_shell_appends_multi_arg_command(monkeypatch, _config):  # noqa: PT019
    """Verify a multi-element command (the bash-fallback probe) is splatted into argv."""
    # Given a patched nomad binary and an interactive stdin
    run = _patch_binary(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    # When opening a shell with a `sh -c` probe command
    allocio.exec_shell(_config, "alloc-1", "web", ["/bin/sh", "-c", "exec bash || exec sh"])

    # Then every command element trails the alloc id in order
    argv = run.call_args.args[0]
    assert argv[-4:] == ["alloc-1", "/bin/sh", "-c", "exec bash || exec sh"]


def test_stream_logs_default_follows_both_streams(monkeypatch, _config):  # noqa: PT019
    """Verify the default mode follows both streams via Nomad's native interleaving."""
    # Given a patched nomad binary
    run = _patch_binary(monkeypatch)

    # When streaming logs with no stream selection, tail, or export
    allocio.stream_logs(_config, "alloc-1", "web")

    # Then it follows with no stream flag so the binary merges stdout and stderr
    argv = run.call_args.args[0]
    assert argv == ["/usr/bin/nomad", "alloc", "logs", "-f", "-task", "web", "alloc-1"]


def test_stream_logs_follow_single_stream_is_explicit(monkeypatch, _config):  # noqa: PT019
    """Verify selecting one stream passes its explicit flag in follow mode."""
    # Given a patched nomad binary
    run = _patch_binary(monkeypatch)

    # When following only stdout
    allocio.stream_logs(_config, "alloc-1", "web", streams=("stdout",))

    # Then -stdout is passed explicitly alongside -f
    argv = run.call_args.args[0]
    assert argv == ["/usr/bin/nomad", "alloc", "logs", "-f", "-stdout", "-task", "web", "alloc-1"]


def test_stream_logs_stderr_tail_is_static(monkeypatch, _config):  # noqa: PT019
    """Verify a single stream with a tail count produces a static read (no -f)."""
    # Given a patched nomad binary
    run = _patch_binary(monkeypatch)

    # When tailing the last 50 stderr lines
    allocio.stream_logs(_config, "alloc-1", "web", streams=("stderr",), tail=50)

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


def test_stream_logs_export_writes_snapshot(monkeypatch, tmp_path, _config):  # noqa: PT019
    """Verify export captures a single stream and writes it to the file without following."""
    # Given a patched binary that returns log bytes
    run = _patch_binary(monkeypatch, stdout=b"line1\nline2\n")
    out = tmp_path / "web.log"

    # When exporting only stdout
    code = allocio.stream_logs(_config, "alloc-1", "web", streams=("stdout",), export_path=out)

    # Then it captured output (no -f), wrote the file, and reported success
    argv = run.call_args.args[0]
    assert "-f" not in argv
    assert run.call_args.kwargs["capture_output"] is True
    assert out.read_bytes() == b"line1\nline2\n"
    assert code == 0


def test_stream_logs_export_both_concatenates_streams(monkeypatch, tmp_path, _config):  # noqa: PT019
    """Verify exporting both streams reads each in turn and concatenates them."""
    # Given a patched binary that returns log bytes for every read
    run = _patch_binary(monkeypatch, stdout=b"chunk\n")
    out = tmp_path / "web.log"

    # When exporting with the default (both) stream selection
    allocio.stream_logs(_config, "alloc-1", "web", export_path=out)

    # Then both stdout and stderr are read (two calls) and their output is concatenated
    assert run.call_count == 2
    assert out.read_bytes() == b"chunk\nchunk\n"


def test_stream_logs_export_failure_raises(monkeypatch, tmp_path, _config):  # noqa: PT019
    """Verify export raises NomadBinaryError when the binary exits non-zero."""
    # Given a patched binary that fails with stderr
    _patch_binary(monkeypatch, returncode=1, stderr=b"boom")
    out = tmp_path / "web.log"

    # When exporting logs
    with pytest.raises(NomadBinaryError):
        allocio.stream_logs(_config, "alloc-1", "web", streams=("stdout",), export_path=out)

    # Then the export file was not written
    assert not out.exists()


def test_stream_logs_export_with_tail_writes_snapshot(monkeypatch, tmp_path, _config):  # noqa: PT019
    """Verify combined tail and export captures last N lines to file without following."""
    # Given a patched binary that returns log bytes
    run = _patch_binary(monkeypatch, stdout=b"x\n")
    out = tmp_path / "t.log"

    # When exporting only stdout with a tail count
    allocio.stream_logs(_config, "alloc-1", "web", streams=("stdout",), tail=10, export_path=out)

    # Then it includes tail args, does not follow, and writes the file
    argv = run.call_args.args[0]
    assert "-tail" in argv
    assert "-n" in argv
    assert "10" in argv
    assert "-f" not in argv
    assert out.read_bytes() == b"x\n"
