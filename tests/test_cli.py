# type: ignore
"""Test nd CLI."""

from typer.testing import CliRunner

from nd.cli import app

runner = CliRunner()


def test_help() -> None:
    """Test that the help command works as expected."""
    message = "Show this message and exit."
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert message in result.stdout
