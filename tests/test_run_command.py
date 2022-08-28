# type: ignore
"""Test the plan command."""
from pathlib import Path

from nd._commands import run_nomad_job


def test_plan_nomad_job_no_jobs():
    """Test plan_nomad_job when no matching jobs found."""
    assert (
        run_nomad_job(
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
            job_name="zzz",
        )
        is False
    )


def test_plan_nomad_job_one_job(capsys, mocker):
    """Test plan_nomad_job when one matching job found."""
    mocker.patch("nd._commands.utils.job_files.JobFile.validate", return_value=True)
    mocker.patch("nd._commands.utils.job_files.JobFile.plan", return_value="123456")
    mocker.patch("nd._commands.utils.job_files.JobFile.run", return_value=True)

    assert (
        run_nomad_job(
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
            job_name="lidarr",
        )
        is True
    )
    captured = capsys.readouterr().out
    expected = "SUCCESS  | lidarr has been started."
    assert expected in captured


def test_plan_nomad_job_failed_start(mocker):
    """Test plan_nomad_job when job.run fails."""
    mocker.patch("nd._commands.utils.job_files.JobFile.validate", return_value=True)
    mocker.patch("nd._commands.utils.job_files.JobFile.plan", return_value="123456")
    mocker.patch("nd._commands.utils.job_files.JobFile.run", return_value=False)

    assert (
        run_nomad_job(
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
            job_name="lidarr",
        )
        is False
    )
