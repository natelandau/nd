# type: ignore
"""Test status command."""

import re
from pathlib import Path

from nd._commands.status_command import show_cluster_status
from tests.helpers import Regex


def test_show_cluster_status(mock_nodes, mock_jobs, mocker, capsys):
    """Test show_cluster_status."""
    mocker.patch("nd._commands.status_command.populate_nodes", return_value=mock_nodes)
    mocker.patch("nd._commands.status_command.populate_running_jobs", return_value=mock_jobs)
    show_cluster_status(
        verbosity=0,
        dry_run=False,
        log_to_file=False,
        log_file=Path("/dev/null"),
        config={
            "job_files_locations": [
                "tests/resources/job_files/valid",
                "tests/resources/job_files/invalid",
            ],
            "nomad_api_url": "http://junk.url",
        },
    )
    output = capsys.readouterr().out

    assert "Node Name:  node1" in output
    assert "IP Address:  10.0.0.4" in output
    assert "IP Address:  10.0.0.5" in output
    assert "╔═" in output
    assert output == Regex(r"^║ 1 +mock_task1 +.*running +True +║$", re.MULTILINE)
    assert "No running jobs" in output


def test_show_cluster_status_with_no_nodes(mocker):
    """Test show_cluster_status fails without nodes."""
    mocker.patch("nd._commands.status_command.populate_nodes", return_value=[])
    assert (
        show_cluster_status(
            verbosity=0,
            dry_run=False,
            log_to_file=False,
            log_file=Path("/dev/null"),
            config={
                "job_files_locations": [
                    "tests/resources/job_files/valid",
                    "tests/resources/job_files/invalid",
                ],
                "nomad_api_url": "http://junk.url",
            },
        )
        is False
    )


def test_show_cluster_status_with_no_jobs(mocker, mock_nodes):
    """Test show_cluster_status fails without jobs."""
    mocker.patch("nd._commands.status_command.populate_nodes", return_value=mock_nodes)
    mocker.patch("nd._commands.status_command.populate_running_jobs", return_value=[])
    assert (
        show_cluster_status(
            verbosity=0,
            dry_run=False,
            log_to_file=False,
            log_file=Path("/dev/null"),
            config={
                "job_files_locations": [
                    "tests/resources/job_files/valid",
                    "tests/resources/job_files/invalid",
                ],
                "nomad_api_url": "http://junk.url",
            },
        )
        is False
    )
