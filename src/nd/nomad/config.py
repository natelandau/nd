"""Connection configuration for the Nomad API client."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import msgspec

from nd.constants import DEFAULT_NOMAD_ADDRESS, DEFAULT_REQUEST_TIMEOUT_SECONDS
from nd.nomad.errors import NomadConfigError

# Standard Nomad env var -> NomadConfig field name.
_ENV_MAP = {
    "NOMAD_ADDR": "address",
    "NOMAD_TOKEN": "token",
    "NOMAD_NAMESPACE": "namespace",
    "NOMAD_REGION": "region",
    "NOMAD_CACERT": "ca_cert",
    "NOMAD_CLIENT_CERT": "client_cert",
    "NOMAD_CLIENT_KEY": "client_key",
    "NOMAD_TLS_SERVER_NAME": "tls_server_name",
    "NOMAD_UI_URL": "ui_url",
}


class NomadConfig(msgspec.Struct, frozen=True, kw_only=True):
    """Resolved connection settings for the Nomad API."""

    address: str = DEFAULT_NOMAD_ADDRESS
    token: str | None = None
    namespace: str | None = None
    region: str | None = None
    ca_cert: str | None = None
    client_cert: str | None = None
    client_key: str | None = None
    tls_server_name: str | None = None
    ui_url: str | None = None
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS

    @classmethod
    def resolve(cls, config_path: Path | None = None) -> NomadConfig:
        """Resolve config from Nomad env vars, overridden by an nd TOML config file.

        Args:
            config_path: Explicit path to an nd config file. Defaults to the
                XDG config location when omitted.

        Returns:
            The resolved configuration.

        Raises:
            NomadConfigError: If the config file is unreadable or its values are invalid.
        """
        values: dict[str, Any] = {}
        for env_name, field_name in _ENV_MAP.items():
            env_val = os.environ.get(env_name)
            if env_val:
                values[field_name] = env_val

        path = config_path or _default_config_path()
        if path.is_file():
            values.update(_load_config_file(path))

        try:
            return msgspec.convert(values, cls, strict=False)
        except msgspec.ValidationError as exc:
            msg = f"Invalid Nomad configuration: {exc}"
            raise NomadConfigError(msg) from exc


def _default_config_path() -> Path:
    """Return the XDG config path for nd's config file."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "nd" / "config.toml"


def _load_config_file(path: Path) -> dict[str, Any]:
    """Load and validate the ``[nomad]`` table from an nd TOML config file."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f"Could not read config file {path}: {exc}"
        raise NomadConfigError(msg) from exc
    section = data.get("nomad", {})
    if not isinstance(section, dict):
        msg = f"[nomad] section in {path} must be a table"
        raise NomadConfigError(msg)
    return dict(section)
