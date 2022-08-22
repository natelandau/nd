# type: ignore
"""Test the Stop command and method."""
import re
from pathlib import Path

from nd._commands import stop_job


def test_stop_command(mocker, mock_job, capsys, requests_mock):
    """Test stop command."""
    mocker.patch("nd._commands.stop_command.populate_running_jobs", return_value=mock_job)

    stop_url = re.compile(r".*/job/.*")
    requests_mock.delete(stop_url, text="")
    assert (
        stop_job(
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
            job_name="job1",
            no_clean=True,
        )
        is True
    )
    output = capsys.readouterr().out
    assert "SUCCESS  | Stopped job: job1" in output

    assert (
        stop_job(
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
            job_name="job1",
            no_clean=False,
        )
        is True
    )
    output = capsys.readouterr().out
    assert "SUCCESS  | Stopped job: job1" in output
