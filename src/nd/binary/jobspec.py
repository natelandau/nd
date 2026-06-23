"""Wrappers around the `nomad` binary for HCL2 compilation and validation.

The Nomad HTTP API cannot parse HCL2, so the local `nomad` binary is used as the
HCL2 -> JSON compiler and validator. Everything else goes through the API client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nclutils.sh import ShellCommandError, run_command

from nd.binary.env import NomadBinaryError, binary_env

if TYPE_CHECKING:
    from pathlib import Path

    from nd.nomad.config import NomadConfig


def validate(file: Path, config: NomadConfig, *, nomad_bin: Path) -> None:
    """Validate a job file with `nomad job validate`.

    ``nomad_bin`` is the resolved binary path from :func:`ensure_nomad`, passed in by
    the caller so a multi-file run resolves the binary once rather than per file.

    Raises:
        NomadBinaryError: If validation fails or the binary cannot run.
    """
    try:
        run_command([str(nomad_bin), "job", "validate", str(file)], env=binary_env(config))
    except ShellCommandError as exc:
        detail = _stderr(exc)
        msg = f"`nomad job validate {file}` failed: {detail}"
        raise NomadBinaryError(msg) from exc


def plan(file: Path, config: NomadConfig, *, nomad_bin: Path) -> int:
    """Preview a job with `nomad job plan`, streaming its output verbatim.

    ``nomad_bin`` is the resolved binary path from :func:`ensure_nomad`, passed in by
    the caller so a multi-file run resolves the binary once rather than per file.
    Returns the binary's exit code (1 means changes are present, 0 means none).

    Raises:
        NomadBinaryError: If the binary cannot be launched.
    """
    try:
        result = run_command(
            [str(nomad_bin), "job", "plan", str(file)],
            env=binary_env(config),
            stream=True,
            check=False,
        )
    except ShellCommandError as exc:
        msg = f"`nomad job plan {file}` could not run: {_stderr(exc)}"
        raise NomadBinaryError(msg) from exc
    return result.returncode


def compile_to_json(file: Path, config: NomadConfig, *, nomad_bin: Path) -> bytes:
    """Compile a job file to its JSON register payload via `nomad job run -output`.

    ``nomad_bin`` is the resolved binary path from :func:`ensure_nomad`, passed in by
    the caller so a multi-file run resolves the binary once rather than per file.
    Returns the ``{"Job": {...}}`` JSON bytes without submitting anything.

    Raises:
        NomadBinaryError: If compilation fails.
    """
    try:
        result = run_command(
            [str(nomad_bin), "job", "run", "-output", str(file)], env=binary_env(config)
        )
    except ShellCommandError as exc:
        msg = f"`nomad job run -output {file}` failed: {_stderr(exc)}"
        raise NomadBinaryError(msg) from exc
    return result.stdout.encode("utf-8")


def _stderr(exc: ShellCommandError) -> str:
    """Extract stderr (or the message) from a shell error for a friendly report."""
    result = getattr(exc, "result", None)
    if result is not None and getattr(result, "stderr", ""):
        return result.stderr.strip()
    return str(exc)
