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


def test_list() -> None:
    """Test that the list command works as expected."""
    result = runner.invoke(app, ["--config-file", "tests/resources/config_all.toml", "list"])
    assert result.exit_code == 0
    assert "tests/resources/job_files/valid/lidarr.hcl" in result.stdout
    assert "tests/resources/job_files/invalid/sonarr.txt" not in result.stdout
    assert "nojob.hcl" not in result.stdout
    assert "Local Backup" not in result.stdout

    result2 = runner.invoke(
        app, ["-vv", "--config-file", "tests/resources/config_all.toml", "list"]
    )
    assert result2.exit_code == 0
    assert "tests/resources/job_files/valid/lidarr.hcl" in result2.stdout
    assert "tests/resources/job_files/invalid/sonarr.txt" not in result2.stdout
    assert "nojob.hcl" not in result2.stdout
    assert "Local Backup" in result2.stdout


def test_list_fail() -> None:
    """Test that the list command works as expected."""
    result = runner.invoke(app, ["--config-file", "tests/resources/config_no_jobs.toml", "list"])
    assert result.exit_code == 1
    assert "No valid job files found in /dev/null " in result.stdout
