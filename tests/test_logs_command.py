# type: ignore
"""Test the logs command."""
import re
from pathlib import Path

from nd._commands import view_logs
from tests.helpers import Regex


def test_single_command(mock_job, capsys, mocker):
    """Test that a single command is executed."""
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
            task_name="mock_task1",
        )
        is True
    )
    output = capsys.readouterr().out

    assert output == Regex(
        r"nomad.*alloc.*logs.*-f.*-n.*50.*36be6d11.*mock_task1",
        re.DOTALL + re.MULTILINE,
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
