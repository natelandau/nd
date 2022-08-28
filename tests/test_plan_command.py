# type: ignore
"""Test the plan command."""
from pathlib import Path

from nd._commands import plan_nomad_job


def test_plan_nomad_job_no_jobs():
    """Test plan_nomad_job when no matching jobs found."""
    assert (
        plan_nomad_job(
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
    mocker.patch("nd._utils.job_files.JobFile.validate", return_value=True)
    mocker.patch("nd._utils.job_files.JobFile.plan", return_value="123456")

    plan_nomad_job(
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
    captured = capsys.readouterr()
    expected = "lidarr │ nomad job run -check-index 123456"
    assert expected in captured.out


def test_plan_nomad_job_many_jobs(capsys, mocker):
    """Test plan_nomad_job when many matching jobs found."""
    mocker.patch("nd._utils.job_files.JobFile.validate", return_value=True)
    mocker.patch("nd._utils.job_files.JobFile.plan", return_value="123456")

    plan_nomad_job(
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
        job_name="arr",
    )
    print(capsys.readouterr().out)

    captured = capsys.readouterr().out
    expected = "lidarr │ nomad job run -check-index 123456"
    expected2 = "sonarr │ nomad job run -check-index 123456"
    expected3 = "2 jobs planned"
    assert expected in captured
    assert expected2 in captured
    assert expected3 in captured
