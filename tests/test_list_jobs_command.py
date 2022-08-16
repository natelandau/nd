# type: ignore
"""Test list_jobs command."""
from pathlib import Path

from nd._commands.list_jobs_command import show_jobs
from nd._commands.utils.job_files import JobFile


def test_list_jobs_many(capsys, mocker):
    """Test list_jobs command with many jobs."""
    job1 = JobFile(
        name="test1",
        file=Path("tests/resources/job_files/valid/test1.hcl"),
        local_backup=False,
    )
    job2 = JobFile(
        name="test2",
        file=Path("tests/resources/job_files/valid/test2.hcl"),
        local_backup=False,
    )

    mocker.patch("nd._commands.list_jobs_command.list_valid_jobs", return_value=[job1, job2])

    show_jobs(
        verbosity=0,
        dry_run=False,
        log_to_file=False,
        log_file=Path("/dev/null"),
        config={
            "job_files_locations": [
                "tests/resources/job_files/valid",
                "tests/resources/job_files/invalid",
            ]
        },
    )

    expected1 = "test1 │ tests/resources/job_files/valid/test1.hcl"
    expected2 = "test2 │ tests/resources/job_files/valid/test2.hcl"
    expected3 = "2 valid Nomad jobs found."
    result = capsys.readouterr().out
    assert expected1 in result
    assert expected2 in result
    assert expected3 in result


def test_list_jobs_one(capsys, mocker):
    """Test list_jobs command with one job."""
    job1 = JobFile(
        name="test1",
        file=Path("tests/resources/job_files/valid/test1.hcl"),
        local_backup=False,
    )

    mocker.patch("nd._commands.list_jobs_command.list_valid_jobs", return_value=[job1])

    show_jobs(
        verbosity=0,
        dry_run=False,
        log_to_file=False,
        log_file=Path("/dev/null"),
        config={
            "job_files_locations": [
                "tests/resources/job_files/valid",
                "tests/resources/job_files/invalid",
            ]
        },
        job_name="test1",
    )

    expected1 = "test1 │ tests/resources/job_files/valid/test1.hcl"
    expected2 = "1 valid Nomad jobs found."
    result = capsys.readouterr().out
    assert expected1 in result
    assert expected2 in result


def test_list_jobs_none(mocker):
    """Test list_jobs command with no jobs."""
    mocker.patch("nd._commands.list_jobs_command.list_valid_jobs", side_effect=AssertionError)

    assert (
        show_jobs(
            verbosity=0,
            dry_run=False,
            log_to_file=False,
            log_file=Path("/dev/null"),
            config={
                "job_files_locations": [
                    "tests/resources/job_files/valid",
                    "tests/resources/job_files/invalid",
                ]
            },
        )
        is False
    )
