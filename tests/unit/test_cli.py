"""Tests for the root CLI app."""

import sys

import httpx2
import pytest
import respx

from nd import __version__
from nd.cli import app, main
from nd.nomad import NomadAuthError, NomadConfigError, NomadError, NomadServerError
from nd.targets import SelectionError
from nd.ui.prompts import PromptUnavailableError
from tests.helpers import NOMAD_TEST_ADDR, capture_output


def test_cli_version_prints_and_exits(typer_runner):
    """Verify --version prints the package version and exits zero."""
    # Given the root app
    # When invoking with --version
    result = typer_runner.invoke(app, ["--version"])

    # Then it exits cleanly and prints the version
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_dash_h_shows_help(typer_runner):
    """Verify -h is accepted as an alias for --help across the CLI."""
    # Given the root app
    # When invoking with -h
    result = typer_runner.invoke(app, ["-h"])

    # Then it exits cleanly and shows usage
    assert result.exit_code == 0
    assert "Usage:" in result.output


@pytest.mark.parametrize(
    ("args", "renderer"),
    [
        pytest.param([], "render_report", id="bare"),
        pytest.param(["-v"], "render_report", id="root-verbose"),
        pytest.param(["--hosts"], "render_hosts", id="status-option"),
        pytest.param(["-vv", "--hosts"], "render_hosts", id="root-verbose-then-status-option"),
        pytest.param(["--hosts", "-v"], "render_hosts", id="status-option-then-verbose"),
    ],
)
def test_cli_no_subcommand_runs_status(mocker, typer_runner, args: list[str], renderer: str):
    """Verify nd without a subcommand runs the status dashboard, accepting status options."""
    # Given the real status callback runs but its cluster query and rendering are stubbed
    collect_mock = mocker.patch("nd.commands.status.command._collect")
    collect_mock.return_value = (mocker.MagicMock(), [])
    render_mock = mocker.patch(f"nd.commands.status.command.{renderer}")

    # When invoking the root app without naming a subcommand
    result = typer_runner.invoke(app, args)

    # Then the matching status view is collected and rendered
    assert result.exit_code == 0, result.output
    assert collect_mock.called
    assert render_mock.called


def test_cli_status_option_on_other_subcommand_is_rejected(typer_runner):
    """Verify a status-only option after another subcommand fails instead of being ignored."""
    # Given the root app
    # When passing --hosts to a subcommand that does not declare it
    result = typer_runner.invoke(app, ["list", "--hosts"])

    # Then the CLI reports a usage error
    assert result.exit_code == 2
    assert "--hosts" in result.output


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


@pytest.mark.usefixtures("nomad_env")
def test_main_maps_connection_error_to_clean_exit(httpx2_mock: respx.Router, monkeypatch):
    """Verify an unreachable agent exits non-zero instead of dumping a traceback."""
    # Given every endpoint failing at the transport level
    for path in (
        "/v1/nodes",
        "/v1/jobs",
        "/v1/allocations",
        "/v1/agent/members",
        "/v1/status/leader",
        "/v1/deployments",
        "/v1/evaluations",
    ):
        httpx2_mock.get(f"{NOMAD_TEST_ADDR}{path}").mock(
            side_effect=httpx2.ConnectError("unreachable")
        )
    monkeypatch.setattr(sys, "argv", ["nd", "status"])

    # When running main()
    # Then it exits with a non-zero status code
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(PromptUnavailableError("Selection requires a terminal"), id="no-terminal"),
        pytest.param(SelectionError("No running job matching 'zzz'"), id="no-match"),
        pytest.param(
            NomadAuthError("denied", status_code=403, method="GET", path="/jobs", body=""),
            id="auth",
        ),
        pytest.param(NomadConfigError("bad config"), id="config"),
        pytest.param(
            NomadServerError("boom", status_code=500, method="GET", path="/jobs", body=""),
            id="other-nomad-error",
        ),
        pytest.param(NomadError("decode failed"), id="base-nomad-error"),
        pytest.param(
            ExceptionGroup("view", [ExceptionGroup("readers", [NomadError("stream lost")])]),
            id="nested-group-of-nomad-errors",
        ),
    ],
)
def test_main_maps_expected_errors_to_exit_one(mocker, error: Exception):
    """Verify every expected failure exits 1 with a message instead of a traceback."""
    # Given a command that fails with an error main() knows how to report
    mocker.patch("nd.cli.app", side_effect=error)

    # When running main()
    # Then it exits 1 rather than letting the exception escape
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ValueError("bug"), id="bare-error"),
        pytest.param(
            ExceptionGroup("view", [NomadError("stream lost"), ValueError("bug")]),
            id="group-with-a-non-nomad-error",
        ),
    ],
)
def test_main_lets_unexpected_errors_escape(mocker, error: Exception):
    """Verify a bug surfaces as its own exception instead of a misleading clean exit."""
    # Given a command that fails with an error main() does not handle
    mocker.patch("nd.cli.app", side_effect=error)

    # When running main()
    # Then the error propagates unchanged
    with pytest.raises(type(error)) as raised:
        main()
    assert raised.value is error


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            SelectionError("No task 'x'; its tasks are: web\x1b]52;c;cm0gLXJm\x07"), id="selection"
        ),
        pytest.param(
            NomadServerError(
                "boom\x1bc", status_code=500, method="GET", path="/jobs", body="\x1b]0;title\x07"
            ),
            id="nomad-error",
        ),
    ],
)
def test_main_strips_terminal_controls_from_errors(mocker, error: Exception):
    """Verify cluster text in an error message cannot send escape sequences to the terminal."""
    # Given a command that fails with an error carrying escape sequences
    console = capture_output()
    mocker.patch("nd.cli.app", side_effect=error)

    # When running main()
    with pytest.raises(SystemExit):
        main()

    # Then no escape sequence from the error reaches the output
    output = console.export_text(styles=False)
    assert "]52;" not in output
    assert "]0;title" not in output
    assert "\x1bc" not in output
