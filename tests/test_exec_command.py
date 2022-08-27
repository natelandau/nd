# type: ignore
"""Test the exec command."""

from pathlib import Path

from nd._commands import exec_in_container


def test_single_command(mock_job, mocker):
    """Test that a single command is executed."""
    mocker.patch("nd._commands.exec_command.populate_running_jobs", return_value=mock_job)

    mocker.patch("nd._commands.utils.cluster_placements.Task.execute", return_value=True)

    assert (
        exec_in_container(
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
            task_name="mock_task1",
            exec_command="echo 'hello world'",
        )
        is True
    )


def test_failed_commandd(mock_job, mocker):
    """Test that a single command is executed."""
    mocker.patch("nd._commands.exec_command.populate_running_jobs", return_value=mock_job)

    mocker.patch("nd._commands.utils.cluster_placements.Task.execute", return_value=False)

    assert (
        exec_in_container(
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
            task_name="mock_task1",
            exec_command=None,
        )
        is False
    )


def test_no_results(mocker, mock_job):
    """Test that no results are returned."""
    mocker.patch("nd._commands.exec_command.populate_running_jobs", return_value=mock_job)

    assert (
        exec_in_container(
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
            task_name="not exist",
            exec_command="echo 'hello world'",
        )
        is False
    )
