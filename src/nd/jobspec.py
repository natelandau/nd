"""Wrappers around the `nomad` binary for HCL2 compilation and validation.

The Nomad HTTP API cannot parse HCL2, so the local `nomad` binary is used as the
HCL2 -> JSON compiler and validator. Everything else goes through the API client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nclutils.sh import ShellCommandError, run_command, which

if TYPE_CHECKING:
    from pathlib import Path


class JobSpecError(Exception):
    """Raised when the `nomad` binary is missing or a `nomad` invocation fails."""


def ensure_nomad() -> Path:
    """Return the path to the `nomad` binary, or raise if it is not on PATH."""
    found = which("nomad")
    if found is None:
        msg = "The `nomad` binary was not found on PATH; install it to plan or run jobs."
        raise JobSpecError(msg)
    return found


def validate(file: Path) -> None:
    """Validate a job file with `nomad job validate`.

    Raises:
        JobSpecError: If the binary is missing or validation fails.
    """
    ensure_nomad()
    try:
        run_command(["nomad", "job", "validate", str(file)])
    except ShellCommandError as exc:
        detail = _stderr(exc)
        msg = f"`nomad job validate {file}` failed: {detail}"
        raise JobSpecError(msg) from exc


def plan(file: Path) -> int:
    """Preview a job with `nomad job plan`, streaming its output verbatim.

    Returns the binary's exit code (1 means changes are present, 0 means none).

    Raises:
        JobSpecError: If the binary is missing or cannot be launched.
    """
    ensure_nomad()
    try:
        result = run_command(
            ["nomad", "job", "plan", str(file)],
            stream=True,
            check=False,
        )
    except ShellCommandError as exc:
        msg = f"`nomad job plan {file}` could not run: {_stderr(exc)}"
        raise JobSpecError(msg) from exc
    return result.returncode


def compile_to_json(file: Path) -> bytes:
    """Compile a job file to its JSON register payload via `nomad job run -output`.

    Returns the ``{"Job": {...}}`` JSON bytes without submitting anything.

    Raises:
        JobSpecError: If the binary is missing or compilation fails.
    """
    ensure_nomad()
    try:
        result = run_command(["nomad", "job", "run", "-output", str(file)])
    except ShellCommandError as exc:
        msg = f"`nomad job run -output {file}` failed: {_stderr(exc)}"
        raise JobSpecError(msg) from exc
    return result.stdout.encode("utf-8")


def _stderr(exc: ShellCommandError) -> str:
    """Extract stderr (or the message) from a shell error for a friendly report."""
    result = getattr(exc, "result", None)
    if result is not None and getattr(result, "stderr", ""):
        return result.stderr.strip()
    return str(exc)
