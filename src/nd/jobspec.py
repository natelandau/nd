"""Wrappers around the `nomad` binary for HCL2 compilation and validation.

The Nomad HTTP API cannot parse HCL2, so the local `nomad` binary is used as the
HCL2 -> JSON compiler and validator. Everything else goes through the API client.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from nclutils.sh import ShellCommandError, run_command, which

if TYPE_CHECKING:
    from pathlib import Path

    from nd.nomad.config import NomadConfig


class JobSpecError(Exception):
    """Raised when the `nomad` binary is missing or a `nomad` invocation fails."""


def ensure_nomad() -> Path:
    """Return the path to the `nomad` binary, or raise if it is not on PATH."""
    found = which("nomad")
    if found is None:
        msg = "The `nomad` binary was not found on PATH; install it to plan or run jobs."
        raise JobSpecError(msg)
    return found


def binary_env(config: NomadConfig) -> dict[str, str]:
    """Build the environment for a `nomad` binary invocation.

    Overlays the resolved connection settings onto the current environment so the
    spawned binary targets the same cluster, token, and namespace as the API client
    rather than relying on the ambient env alone (which would miss nd config-file
    overrides). Shared with ``allocio`` so every binary wrapper stays consistent.
    """
    return {**os.environ, **config.to_env()}


def validate(file: Path, config: NomadConfig, *, nomad_bin: Path) -> None:
    """Validate a job file with `nomad job validate`.

    ``nomad_bin`` is the resolved binary path from :func:`ensure_nomad`, passed in by
    the caller so a multi-file run resolves the binary once rather than per file.

    Raises:
        JobSpecError: If validation fails or the binary cannot run.
    """
    try:
        run_command([str(nomad_bin), "job", "validate", str(file)], env=binary_env(config))
    except ShellCommandError as exc:
        detail = _stderr(exc)
        msg = f"`nomad job validate {file}` failed: {detail}"
        raise JobSpecError(msg) from exc


def plan(file: Path, config: NomadConfig, *, nomad_bin: Path) -> int:
    """Preview a job with `nomad job plan`, streaming its output verbatim.

    ``nomad_bin`` is the resolved binary path from :func:`ensure_nomad`, passed in by
    the caller so a multi-file run resolves the binary once rather than per file.
    Returns the binary's exit code (1 means changes are present, 0 means none).

    Raises:
        JobSpecError: If the binary cannot be launched.
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
        raise JobSpecError(msg) from exc
    return result.returncode


def compile_to_json(file: Path, config: NomadConfig, *, nomad_bin: Path) -> bytes:
    """Compile a job file to its JSON register payload via `nomad job run -output`.

    ``nomad_bin`` is the resolved binary path from :func:`ensure_nomad`, passed in by
    the caller so a multi-file run resolves the binary once rather than per file.
    Returns the ``{"Job": {...}}`` JSON bytes without submitting anything.

    Raises:
        JobSpecError: If compilation fails.
    """
    try:
        result = run_command(
            [str(nomad_bin), "job", "run", "-output", str(file)], env=binary_env(config)
        )
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
