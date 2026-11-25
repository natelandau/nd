"""Tests for Nomad connection config resolution."""

from pathlib import Path

import pytest

from nd.constants import DEFAULT_NOMAD_ADDRESS
from nd.nomad.config import NomadConfig, load_config_directories
from nd.nomad.errors import NomadConfigError


def test_resolve_defaults_address_when_unset(tmp_path):
    """Verify resolve falls back to the default address when nothing is set."""
    # Given no env vars and no config file
    # When resolving config
    cfg = NomadConfig.resolve(config_path=tmp_path / "missing.toml")

    # Then the default address is used and the token is unset
    assert cfg.address == DEFAULT_NOMAD_ADDRESS
    assert cfg.token is None


def test_resolve_reads_env(tmp_path, monkeypatch):
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


@pytest.mark.parametrize(
    ("env_address", "cli_address", "expected"),
    [
        (None, None, "https://from-file:4646"),
        ("https://from-env:4646", None, "https://from-env:4646"),
        ("https://from-env:4646", "https://from-cli:4646", "https://from-cli:4646"),
        (None, "https://from-cli:4646", "https://from-cli:4646"),
    ],
)
def test_resolve_precedence_cli_over_env_over_file(
    tmp_path, monkeypatch, env_address, cli_address, expected
):
    """Verify CLI overrides beat env vars, which beat the config file, per setting."""
    # Given a config file setting address and timeout, and an env token
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[nomad]\naddress = "https://from-file:4646"\ntimeout = 12.5\n')
    monkeypatch.setenv("NOMAD_TOKEN", "env-token")
    if env_address is not None:
        monkeypatch.setenv("NOMAD_ADDR", env_address)

    # When resolving config, with an unset CLI flag passed as None
    cfg = NomadConfig.resolve(config_path=cfg_file, cli_overrides={"address": cli_address})

    # Then the highest-precedence address wins and settings from other layers survive
    assert cfg.address == expected
    assert cfg.token == "env-token"  # noqa: S105
    assert cfg.timeout == 12.5


def test_resolve_collects_every_invalid_value(tmp_path):
    """Verify every invalid setting is reported in one error naming its source."""
    # Given a config file with a bad timeout and a bad address
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[nomad]\naddress = 5\ntimeout = "abc"\n')

    # When resolving config
    # Then one error names both settings and the file they came from
    with pytest.raises(NomadConfigError) as exc_info:
        NomadConfig.resolve(config_path=cfg_file)
    message = str(exc_info.value)
    assert "`timeout`" in message
    assert "`address`" in message
    assert str(cfg_file) in message


def test_resolve_ignores_empty_env_var(tmp_path, monkeypatch):
    """Verify an empty env var does not override the config file."""
    # Given a config file address and an empty NOMAD_ADDR
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[nomad]\naddress = "https://from-file:4646"\n')
    monkeypatch.setenv("NOMAD_ADDR", "")

    # When resolving config
    cfg = NomadConfig.resolve(config_path=cfg_file)

    # Then the file value is used
    assert cfg.address == "https://from-file:4646"


def test_resolve_reads_ui_url_from_env(tmp_path, monkeypatch):
    """Verify resolve reads the optional web UI base URL from the environment."""
    # Given a UI URL env var
    monkeypatch.setenv("NOMAD_UI_URL", "https://nomad.example.org")

    # When resolving config
    cfg = NomadConfig.resolve(config_path=tmp_path / "missing.toml")

    # Then the ui_url is populated
    assert cfg.ui_url == "https://nomad.example.org"


def test_resolve_invalid_config_file_raises(tmp_path):
    """Verify malformed TOML surfaces as a NomadConfigError."""
    # Given a config file with invalid TOML
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("this is = not valid = toml")

    # When resolving config
    # Then a NomadConfigError is raised
    with pytest.raises(NomadConfigError):
        NomadConfig.resolve(config_path=cfg_file)


def test_to_env_includes_set_fields_and_omits_ui_url():
    """Verify to_env emits NOMAD_* vars for set fields and never NOMAD_UI_URL."""
    # Given a config with an address, token, namespace, and a ui_url override
    config = NomadConfig(
        address="http://nomad.test:4646",
        token="abc",  # noqa: S106
        namespace="prod",
        ui_url="http://ui.test",
    )

    # When rendering it as environment variables
    env = config.to_env()

    # Then the connection fields are present and the binary-irrelevant ui_url is not
    assert env["NOMAD_ADDR"] == "http://nomad.test:4646"
    assert env["NOMAD_TOKEN"] == "abc"  # noqa: S105
    assert env["NOMAD_NAMESPACE"] == "prod"
    assert "NOMAD_UI_URL" not in env


def test_to_env_omits_unset_optional_fields():
    """Verify unset optional fields produce no environment entries."""
    # Given a config with only the default address set
    config = NomadConfig(address="http://nomad.test:4646")

    # When rendering it as environment variables
    env = config.to_env()

    # Then no optional connection vars are emitted
    assert "NOMAD_TOKEN" not in env
    assert "NOMAD_NAMESPACE" not in env
    assert "NOMAD_CLIENT_CERT" not in env


def test_load_config_directories_missing_table_is_empty(tmp_path: Path) -> None:
    """Verify a config without the requested table yields no directories."""
    # Given a config file with no [jobs] table
    cfg = tmp_path / "config.toml"
    cfg.write_text('[nomad]\naddress = "http://x:4646"\n', encoding="utf-8")

    # When reading the [jobs] directories
    # Then none are returned
    assert load_config_directories(section="jobs", config_path=cfg) == []


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("[jobs\ndirectories = ", id="malformed-toml"),
        pytest.param('jobs = "not a table"\n', id="section-not-a-table"),
        pytest.param('[jobs]\ndirectories = "string"\n', id="directories-not-a-list"),
    ],
)
def test_load_config_directories_rejects_invalid_config(tmp_path: Path, content: str) -> None:
    """Verify an unreadable config or a wrongly typed section raises NomadConfigError."""
    # Given a config file with an invalid [jobs] section
    cfg = tmp_path / "config.toml"
    cfg.write_text(content, encoding="utf-8")

    # When reading the [jobs] directories
    # Then a config error is raised
    with pytest.raises(NomadConfigError):
        load_config_directories(section="jobs", config_path=cfg)
