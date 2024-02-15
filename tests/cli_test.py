# type: ignore
"""Test nd CLI."""


from typer.testing import CliRunner

from nd.cli import app
from tests.helpers import Regex

runner = CliRunner()


def test_version():
    """Test printing version and then exiting."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output == Regex(r"nd version: \d+\.\d+\.\d+$")
