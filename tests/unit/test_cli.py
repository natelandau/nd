"""Tests for the root CLI app."""

import sys

import httpx2
import pytest
import respx
from typer.testing import CliRunner

from nd import __version__
from nd.cli import app, main

_ADDR = "http://nomad.test:4646"


def test_cli_version_prints_and_exits():
    """Verify --version prints the package version and exits zero."""
    # Given the root app
    # When invoking with --version
    result = CliRunner().invoke(app, ["--version"])

    # Then it exits cleanly and prints the version
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_dash_h_shows_help():
    """Verify -h is accepted as an alias for --help across the CLI."""
    # Given the root app
    # When invoking with -h
    result = CliRunner().invoke(app, ["-h"])

    # Then it exits cleanly and shows usage
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_main_maps_connection_error_to_clean_exit(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify an unreachable agent exits non-zero instead of dumping a traceback."""
    # Given every endpoint failing at the transport level
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for path in (
        "/v1/nodes",
        "/v1/jobs",
        "/v1/allocations",
        "/v1/agent/members",
        "/v1/status/leader",
        "/v1/deployments",
        "/v1/evaluations",
    ):
        httpx2_mock.get(f"{_ADDR}{path}").mock(side_effect=httpx2.ConnectError("unreachable"))
    monkeypatch.setattr(sys, "argv", ["nd", "status"])

    # When running main()
    # Then it exits with a non-zero status code
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1
