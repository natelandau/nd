"""A configured handle to the local `nomad` binary, used where the HTTP API can't serve.

The HTTP API cannot parse HCL2 and does not own the raw-TTY exec protocol, so some
operations shell out to the local `nomad` binary. `NomadBinary` binds the resolved
binary path and the connection-env overlay (which targets the same cluster as the API
client) to one object, so a multi-file deploy or a long exec/log session resolves the
binary and builds the env once rather than per call.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from nclutils import pp
from nclutils.sh import ShellCommandError, run_command

from nd.binary.env import NomadBinaryError, binary_env, ensure_nomad

if TYPE_CHECKING:
    from pathlib import Path

    from nd.nomad.config import NomadConfig


class NomadBinary:
    """The local `nomad` CLI, bound to one cluster's connection settings.

    Build it with :meth:`create`, which resolves the binary on PATH. The job-spec
    methods (`validate`/`plan`/`compile_to_json`) act on local HCL2 files; the
    allocation methods (`exec_shell`/`stream_logs`) act on a running task.
    """

    def __init__(self, config: NomadConfig, path: Path) -> None:
        self._path = str(path)
        # Build the connection-env overlay once; it is invariant for this cluster.
        self._env = binary_env(config)

    @classmethod
    def create(cls, config: NomadConfig) -> NomadBinary:
        """Resolve the `nomad` binary on PATH and bind it to ``config``.

        Raises:
            NomadBinaryError: If the binary is not on PATH.
        """
        return cls(config, ensure_nomad())

    # --- job specs (HCL2 compile/validate) -------------------------------------------

    def validate(self, file: Path) -> None:
        """Validate a job file with `nomad job validate`.

        Raises:
            NomadBinaryError: If validation fails or the binary cannot run.
        """
        try:
            run_command([self._path, "job", "validate", str(file)], env=self._env)
        except ShellCommandError as exc:
            msg = f"`nomad job validate {file}` failed: {_stderr(exc)}"
            raise NomadBinaryError(msg) from exc

    def plan(self, file: Path) -> int:
        """Preview a job with `nomad job plan`, streaming its output verbatim.

        Returns the binary's exit code (1 means changes are present, 0 means none).

        Raises:
            NomadBinaryError: If the binary cannot be launched.
        """
        try:
            result = run_command(
                [self._path, "job", "plan", str(file)], env=self._env, stream=True, check=False
            )
        except ShellCommandError as exc:
            msg = f"`nomad job plan {file}` could not run: {_stderr(exc)}"
            raise NomadBinaryError(msg) from exc
        return result.returncode

    def compile_to_json(self, file: Path) -> bytes:
        """Compile a job file to its JSON register payload via `nomad job run -output`.

        Returns the ``{"Job": {...}}`` JSON bytes without submitting anything.

        Raises:
            NomadBinaryError: If compilation fails.
        """
        try:
            result = run_command([self._path, "job", "run", "-output", str(file)], env=self._env)
        except ShellCommandError as exc:
            msg = f"`nomad job run -output {file}` failed: {_stderr(exc)}"
            raise NomadBinaryError(msg) from exc
        return result.stdout.encode("utf-8")

    # --- allocations (interactive exec, log streaming) -------------------------------

    def exec_shell(self, alloc_id: str, task: str, command: list[str]) -> int:
        """Run an interactive command (a shell) inside a running task via `nomad alloc exec`.

        ``command`` is the in-container argv to launch, e.g. ``["/bin/bash"]`` or the
        ``["/bin/sh", "-c", ...]`` bash-with-fallback probe. Inherits the parent
        terminal's stdio so the session is fully interactive. Returns the exit code.
        """
        argv = [self._path, "alloc", "exec", "-task", task, "-i"]
        # Only request a pseudo-tty when stdin is a real terminal; forcing -t against a
        # pipe (CI, `nd exec ... | cat`) makes the binary fail or hang allocating a PTY.
        if sys.stdin.isatty():
            argv.append("-t")
        argv += [alloc_id, *command]
        pp.debug("exec: " + " ".join(argv))
        completed = subprocess.run(argv, env=self._env, check=False)  # noqa: S603
        return completed.returncode

    def stream_logs(
        self,
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
            NomadBinaryError: If a read fails.
        """
        if tail is None and export_path is None:
            argv = [self._path, "alloc", "logs", "-f"]
            # One stream -> select it explicitly; both -> omit the flag so Nomad
            # interleaves stdout and stderr (its native `-f` behavior).
            if len(streams) == 1:
                argv.append(f"-{streams[0]}")
            argv += ["-task", task, alloc_id]
            pp.debug("logs: " + " ".join(argv))
            # Log streaming is one-way output; detach stdin so it never inherits the
            # parent's terminal or a broken pipe.
            completed = subprocess.run(  # noqa: S603
                argv, env=self._env, stdin=subprocess.DEVNULL, check=False
            )
            return completed.returncode

        # One-shot tail/export: read each requested stream in turn (Nomad cannot merge
        # streams without -f).
        chunks: list[bytes] = []
        exit_code = 0
        for stream in streams:
            argv = [self._path, "alloc", "logs"]
            if tail is not None:
                argv += ["-tail", "-n", str(tail)]
            argv += [f"-{stream}", "-task", task, alloc_id]
            pp.debug("logs: " + " ".join(argv))
            if export_path is not None:
                completed = subprocess.run(  # noqa: S603
                    argv, env=self._env, stdin=subprocess.DEVNULL, capture_output=True, check=False
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
                    argv, env=self._env, stdin=subprocess.DEVNULL, check=False
                )
                exit_code = exit_code or completed.returncode

        if export_path is not None:
            export_path.write_bytes(b"".join(chunks))
            pp.success(f"Wrote logs to {export_path}")
            return 0
        return exit_code


def _stderr(exc: ShellCommandError) -> str:
    """Extract stderr (or the message) from a shell error for a friendly report."""
    result = getattr(exc, "result", None)
    if result is not None and getattr(result, "stderr", ""):
        return result.stderr.strip()
    return str(exc)
