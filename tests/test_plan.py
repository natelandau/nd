# type: ignore
"""Test the plan command."""
from pathlib import Path

from nd._commands import plan
from nd._commands.utils.job_files import JobFile


def test_plan_no_jobs():
    """Test the plan command when no matching jobs found."""
    assert (
        plan(
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


def test_plan_one_job(monkeypatch, capsys):
    """Test the plan command with a single job."""
    monkeypatch.setattr(JobFile, "validate", lambda x: True)
    monkeypatch.setattr(JobFile, "plan", lambda x: "123456")

    plan(
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


def test_plan_multiple_jobs(monkeypatch, capsys):
    """Test the plan command with a single job."""
    monkeypatch.setattr(JobFile, "validate", lambda x: True)
    monkeypatch.setattr(JobFile, "plan", lambda x: "123456")

    plan(
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
    captured = capsys.readouterr()
    expected = "lidarr │ nomad job run -check-index 123456"
    expected2 = "sonarr │ nomad job run -check-index 123456"
    assert expected in captured.out
    assert expected2 in captured.out
