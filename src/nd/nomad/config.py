"""Connection configuration for the Nomad API client."""

from __future__ import annotations

import os
import tomllib
from collections import ChainMap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import msgspec

from nd.constants import DEFAULT_NOMAD_ADDRESS, DEFAULT_REQUEST_TIMEOUT_SECONDS
from nd.nomad.errors import NomadConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping

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

# Vars handed off to the `nomad` binary: everything in _ENV_MAP except NOMAD_UI_URL,
# which is an nd-only concept the binary does not understand.
_BINARY_ENV_MAP = {var: field for var, field in _ENV_MAP.items() if var != "NOMAD_UI_URL"}


class NomadConfigOverrides(TypedDict, total=False):
    """Connection settings from CLI flags, the highest layer of ``NomadConfig.resolve``.

    A key set to None means the flag was not given, so a lower layer keeps its value.
    """

    address: str | None
    token: str | None
    namespace: str | None
    region: str | None
    ca_cert: str | None
    client_cert: str | None
    client_key: str | None
    tls_server_name: str | None
    ui_url: str | None
    timeout: float | None


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

    @property
    def ui_base(self) -> str:
        """Return the base URL for web UI links, falling back to the API address.

        Use when the browser-facing UI lives at a different URL than the API
        endpoint; otherwise links point at the API address itself.
        """
        return (self.ui_url or self.address).rstrip("/")

    def to_env(self) -> dict[str, str]:
        """Render the connection settings as ``NOMAD_*`` environment variables.

        Reverses the env-var/field mapping used by ``resolve`` so a spawned ``nomad``
        binary targets the same cluster, token, namespace, and TLS material as this
        client. ``NOMAD_UI_URL`` is omitted because the binary does not understand it.
        """
        env: dict[str, str] = {}
        for var, field in _BINARY_ENV_MAP.items():
            value = getattr(self, field)
            if value is not None:
                env[var] = str(value)
        return env

    @classmethod
    def resolve(
        cls,
        config_path: Path | None = None,
        *,
        cli_overrides: NomadConfigOverrides | None = None,
    ) -> NomadConfig:
        """Resolve connection settings from the config file, environment, and CLI.

        Layers apply in order, each overriding the ones before: built-in defaults, the
        ``[nomad]`` table of the nd config file, ``NOMAD_*`` environment variables, then
        CLI overrides. Every invalid value is reported at once so a user fixes them in
        one pass.

        Args:
            config_path: Explicit path to an nd config file. Defaults to the
                XDG config location when omitted.
            cli_overrides: Values from CLI flags. A None value counts as not set.

        Returns:
            The resolved configuration.

        Raises:
            NomadConfigError: If the config file is unreadable or any value is invalid.
        """
        path = config_path or default_config_path()
        layers = ChainMap(
            {
                key: _SourcedValue(value=value, source="CLI flag")
                for key, value in (cli_overrides or {}).items()
                if value is not None
            },
            _read_environment(os.environ),
            _read_nomad_table(path),
        )

        values: dict[str, object] = {}
        errors: list[str] = []
        for key, sourced in layers.items():
            try:
                values[key] = msgspec.convert(sourced.value, type=_FIELD_TYPES[key], strict=False)
            except msgspec.ValidationError as exc:
                errors.append(
                    f"`{key}` from {sourced.source}: {sourced.value!r} is invalid ({exc})"
                )
        if errors:
            raise NomadConfigError("\n".join(sorted(errors)))
        return msgspec.convert(values, type=cls)


def default_config_path() -> Path:
    """Return the XDG config path for nd's config file."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "nd" / "config.toml"


def load_config_directories(section: str, config_path: Path | None = None) -> list[Path]:
    """Read a ``[<section>] directories`` path list from the nd TOML config, expanding ``~``.

    Returns an empty list when the config file or the ``[<section>]`` table is absent.
    Reused by the job-file and volume-file discovery layers.

    Args:
        section: The TOML table name to read (e.g. ``"jobs"`` or ``"volumes"``).
        config_path: Explicit path to an nd config file. Defaults to the XDG config
            location when omitted.

    Returns:
        Expanded Path objects for each configured directory.

    Raises:
        NomadConfigError: If the config cannot be read or the directories value has
            the wrong type.
    """
    path = config_path or default_config_path()
    directories = _read_table(path=path, section=section).get("directories", [])
    if not isinstance(directories, list):
        msg = f"[{section}] directories in {path} must be a list of paths, got {directories!r}"
        raise NomadConfigError(msg)
    return [Path(str(d)).expanduser() for d in directories]


def _read_table(path: Path, section: str) -> dict[str, object]:
    """Return one top-level table of the nd config file, or an empty dict when absent."""
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        msg = f"Could not read config file {path}: {exc}"
        raise NomadConfigError(msg) from exc
    table = data.get(section, {})
    if not isinstance(table, dict):
        msg = f"[{section}] section in {path} must be a table, got {table!r}"
        raise NomadConfigError(msg)
    return table


def _read_nomad_table(path: Path) -> dict[str, _SourcedValue]:
    """Return the known settings from the ``[nomad]`` table, tagged with the file path."""
    table = _read_table(path=path, section="nomad")
    return {
        key: _SourcedValue(value=value, source=str(path))
        for key, value in table.items()
        if key in _FIELD_TYPES
    }


def _read_environment(environ: Mapping[str, str]) -> dict[str, _SourcedValue]:
    """Return the settings set by non-empty ``NOMAD_*`` variables, tagged with the variable."""
    return {
        field: _SourcedValue(value=environ[var], source=f"environment variable {var}")
        for var, field in _ENV_MAP.items()
        if environ.get(var)
    }


@dataclass(frozen=True)
class _SourcedValue:
    """Pair a raw setting value with where it came from, for error messages."""

    value: object
    source: str


_FIELD_TYPES: dict[str, object] = {
    field.name: field.type for field in msgspec.structs.fields(NomadConfig)
}
