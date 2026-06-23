"""Wrappers around the `nomad alloc` binary for interactive exec and log streaming.

Selection runs through the async API client; the interactive exec session and the
log stream are handed off to the local `nomad` binary, which already owns the
raw-TTY WebSocket exec protocol and follow-streaming. Mirrors `jobspec.py`, where
the binary is used because the HTTP API is the wrong tool for the job.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from nclutils import pp

from nd.binary.env import NomadBinaryError, binary_env, ensure_nomad

if TYPE_CHECKING:
    from pathlib import Path

    from nd.nomad.config import NomadConfig


def exec_shell(config: NomadConfig, alloc_id: str, task: str, command: list[str]) -> int:
    """Run an interactive command (a shell) inside a running task via `nomad alloc exec`.

    ``command`` is the in-container argv to launch, e.g. ``["/bin/bash"]`` or the
    ``["/bin/sh", "-c", ...]`` bash-with-fallback probe. Inherits the parent
    terminal's stdio so the session is fully interactive, and injects the resolved
    connection settings so the binary targets the same cluster as the API client.
    Returns the command's exit code.

    Raises:
        NomadBinaryError: If the `nomad` binary is not on PATH.
    """
    nomad_bin = ensure_nomad()
    argv = [str(nomad_bin), "alloc", "exec", "-task", task, "-i"]
    # Only request a pseudo-tty when stdin is a real terminal; forcing -t against a
    # pipe (CI, `nd exec ... | cat`) makes the binary fail or hang allocating a PTY.
    if sys.stdin.isatty():
        argv.append("-t")
    argv += [alloc_id, *command]
    pp.debug("exec: " + " ".join(argv))
    completed = subprocess.run(argv, env=binary_env(config), check=False)  # noqa: S603
    return completed.returncode


def stream_logs(
    config: NomadConfig,
    alloc_id: str,
    task: str,
    *,
    streams: tuple[str, ...] = ("stdout", "stderr"),
    tail: int | None = None,
    export_path: Path | None = None,
) -> int:
    """Stream, tail, or export a task's logs via `nomad alloc logs`.

    ``streams`` selects which of ``stdout``/``stderr`` to read; the default reads both.
    By default follows live until interrupted. ``tail`` shows the last N lines
    statically. ``export_path`` writes the currently-available logs to a file instead
    of streaming. Returns the binary's exit code; for an export, 0 on a successful write.

    In follow mode both streams are read together through Nomad's native interleaving
    (no stream flag, its `-f` default). A tail read or an export is one-shot, and Nomad
    cannot merge streams without `-f`, so each requested stream is read in turn (stdout
    then stderr) and concatenated.

    Raises:
        NomadBinaryError: If the `nomad` binary is not on PATH or a read fails.
    """
    nomad_bin = ensure_nomad()
    env = binary_env(config)

    if tail is None and export_path is None:
        argv = [str(nomad_bin), "alloc", "logs", "-f"]
        # One stream -> select it explicitly; both -> omit the flag so Nomad
        # interleaves stdout and stderr (its native `-f` behavior).
        if len(streams) == 1:
            argv.append(f"-{streams[0]}")
        argv += ["-task", task, alloc_id]
        pp.debug("logs: " + " ".join(argv))
        # Log streaming is one-way output; detach stdin so it never inherits the
        # parent's terminal or a broken pipe.
        completed = subprocess.run(  # noqa: S603
            argv, env=env, stdin=subprocess.DEVNULL, check=False
        )
        return completed.returncode

    # One-shot tail/export: read each requested stream in turn (Nomad cannot merge
    # streams without -f).
    chunks: list[bytes] = []
    exit_code = 0
    for stream in streams:
        argv = [str(nomad_bin), "alloc", "logs"]
        if tail is not None:
            argv += ["-tail", "-n", str(tail)]
        argv += [f"-{stream}", "-task", task, alloc_id]
        pp.debug("logs: " + " ".join(argv))
        if export_path is not None:
            completed = subprocess.run(  # noqa: S603
                argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, check=False
            )
            if completed.returncode != 0:
                detail = completed.stderr.decode("utf-8", "replace").strip()
                msg = f"`nomad alloc logs` failed: {detail}"
                raise NomadBinaryError(msg)
            chunks.append(completed.stdout)
        else:
            # Tail prints straight to the terminal; with both streams this prints
            # stdout's tail then stderr's.
            completed = subprocess.run(  # noqa: S603
                argv, env=env, stdin=subprocess.DEVNULL, check=False
            )
            exit_code = exit_code or completed.returncode

    if export_path is not None:
        export_path.write_bytes(b"".join(chunks))
        pp.success(f"Wrote logs to {export_path}")
        return 0
    return exit_code
