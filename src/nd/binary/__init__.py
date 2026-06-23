"""Wrappers around the local `nomad` binary, used where the HTTP API cannot serve.

`jobspec` compiles and validates HCL2; `allocio` runs interactive exec sessions and
log streams. Both share the binary discovery and connection-env overlay in `env`.
"""

from nd.binary.env import NomadBinaryError, binary_env, ensure_nomad

__all__ = ["NomadBinaryError", "binary_env", "ensure_nomad"]
