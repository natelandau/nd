# type: ignore
"""Test the logs command."""

from pathlib import Path

from nd._commands import view_logs


def test_works(mock_job, mocker):
    """Test that a single command is executed."""
    mocker.patch("nd._commands.logs_command.populate_running_jobs", return_value=mock_job)

    mocker.patch("nd._commands.utils.cluster_placements.Task.logs", return_value=True)

    assert (
        view_logs(
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
        )
        is True
    )


def test_fails(mock_job, mocker):
    """Test that a single command is executed."""
    mocker.patch("nd._commands.logs_command.populate_running_jobs", return_value=mock_job)

    mocker.patch("nd._commands.utils.cluster_placements.Task.logs", return_value=False)

    assert (
        view_logs(
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
        )
        is False
    )


def test_no_command(mock_job, mocker):
    """Test that view_logs fails if no matching task is found."""
    mocker.patch("nd._commands.logs_command.populate_running_jobs", return_value=mock_job)

    assert (
        view_logs(
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
            task_name="nonexistant_task",
        )
        is False
    )
