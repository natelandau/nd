"""Shared discovery and environment for the local `nomad` binary.

The Nomad HTTP API cannot parse HCL2 and does not own the raw-TTY exec protocol, so
some operations shell out to the local `nomad` binary. `NomadBinary` (in `runner.py`)
uses these helpers to locate the binary and build the connection-env overlay that
targets the same cluster as the API client.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from nclutils.sh import which

if TYPE_CHECKING:
    from pathlib import Path

    from nd.nomad.config import NomadConfig


class NomadBinaryError(Exception):
    """Raised when the `nomad` binary is missing or a `nomad` invocation fails."""


def ensure_nomad() -> Path:
    """Return the path to the `nomad` binary, or raise if it is not on PATH."""
    found = which("nomad")
    if found is None:
        msg = "The `nomad` binary was not found on PATH; install it to plan or run jobs."
        raise NomadBinaryError(msg)
    return found


def binary_env(config: NomadConfig) -> dict[str, str]:
    """Build the environment for a `nomad` binary invocation.

    Overlays the resolved connection settings onto the current environment so the
    spawned binary targets the same cluster, token, and namespace as the API client
    rather than relying on the ambient env alone (which would miss nd config-file
    overrides). Shared by every binary wrapper so they stay consistent.
    """
    return {**os.environ, **config.to_env()}
