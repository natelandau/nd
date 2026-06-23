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


def test_cli_no_subcommand_runs_status(mocker):
    """Verify invoking nd with no subcommand defaults to the status dashboard."""
    # Given the real status callback runs but its cluster query and rendering are stubbed
    collect_mock = mocker.patch("nd.commands.status.command._collect")
    render_mock = mocker.patch("nd.commands.status.command.render_report")

    # When invoking the root app with no subcommand
    result = CliRunner().invoke(app, [])

    # Then the status dashboard is collected and rendered
    assert result.exit_code == 0, result.output
    assert collect_mock.called
    assert render_mock.called


def test_stop_command_is_registered():
    """Verify the stop subcommand is wired into the root app."""
    # Given the root CLI app
    # When listing registered typer groups
    names = {group.name for group in app.registered_groups}

    # Then stop is present
    assert "stop" in names


def test_main_handles_keyboard_interrupt(mocker):
    """Verify Ctrl-C during any command exits cleanly with code 130, not a traceback."""
    # Given the CLI raising KeyboardInterrupt mid-run
    mocker.patch("nd.cli.app", side_effect=KeyboardInterrupt)

    # When running main()
    # Then it exits with the conventional SIGINT code instead of propagating
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 130


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
