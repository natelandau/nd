"""Tests for Nomad connection config resolution."""

import pytest

from nd.nomad.config import DEFAULT_ADDRESS, NomadConfig
from nd.nomad.errors import NomadConfigError

_NOMAD_ENV = (
    "NOMAD_ADDR",
    "NOMAD_TOKEN",
    "NOMAD_NAMESPACE",
    "NOMAD_REGION",
    "NOMAD_CACERT",
    "NOMAD_CLIENT_CERT",
    "NOMAD_CLIENT_KEY",
    "NOMAD_TLS_SERVER_NAME",
    "XDG_CONFIG_HOME",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Clear all Nomad environment variables for a hermetic resolution test."""
    for name in _NOMAD_ENV:
        monkeypatch.delenv(name, raising=False)


def test_resolve_defaults_address_when_unset(clean_env, tmp_path):
    """Verify resolve falls back to the default address when nothing is set."""
    # Given no env vars and no config file
    # When resolving config
    cfg = NomadConfig.resolve(config_path=tmp_path / "missing.toml")

    # Then the default address is used and the token is unset
    assert cfg.address == DEFAULT_ADDRESS
    assert cfg.token is None


def test_resolve_reads_env(clean_env, tmp_path, monkeypatch):
    """Verify resolve reads connection settings from Nomad env vars."""
    # Given Nomad env vars are set
    monkeypatch.setenv("NOMAD_ADDR", "https://nomad.example:4646")
    monkeypatch.setenv("NOMAD_TOKEN", "secret")
    monkeypatch.setenv("NOMAD_NAMESPACE", "team-a")

    # When resolving config
    cfg = NomadConfig.resolve(config_path=tmp_path / "missing.toml")

    # Then the values come from the environment
    assert cfg.address == "https://nomad.example:4646"
    assert cfg.token == "secret"  # noqa: S105
    assert cfg.namespace == "team-a"


def test_resolve_config_file_overrides_env(clean_env, tmp_path, monkeypatch):
    """Verify config-file values override env vars while leaving others intact."""
    # Given an env base and a config file overriding only the address
    monkeypatch.setenv("NOMAD_ADDR", "https://from-env:4646")
    monkeypatch.setenv("NOMAD_TOKEN", "env-token")
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[nomad]\naddress = "https://from-file:4646"\ntimeout = 12.5\n')

    # When resolving config
    cfg = NomadConfig.resolve(config_path=cfg_file)

    # Then the file wins on address, the env token survives, and timeout is a float
    assert cfg.address == "https://from-file:4646"
    assert cfg.token == "env-token"  # noqa: S105
    assert cfg.timeout == 12.5


def test_resolve_invalid_config_file_raises(clean_env, tmp_path):
    """Verify malformed TOML surfaces as a NomadConfigError."""
    # Given a config file with invalid TOML
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("this is = not valid = toml")

    # When resolving config
    # Then a NomadConfigError is raised
    with pytest.raises(NomadConfigError):
        NomadConfig.resolve(config_path=cfg_file)
