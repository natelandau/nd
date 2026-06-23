"""Wrappers around the local `nomad` binary, used where the HTTP API cannot serve.

`NomadBinary` is a configured handle to the binary (HCL2 compile/validate, plus
interactive exec and log streaming), bound to one cluster via :meth:`NomadBinary.create`.
"""

from nd.binary.env import NomadBinaryError
from nd.binary.runner import NomadBinary

__all__ = ["NomadBinary", "NomadBinaryError"]
