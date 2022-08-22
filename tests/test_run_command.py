# type: ignore
"""Test the plan command."""
from pathlib import Path

from nd._commands import run_nomad_job
from nd._commands.utils.job_files import JobFile


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


def test_plan_nomad_job_one_job(capsys, monkeypatch):
    """Test plan_nomad_job when one matching job found."""
    monkeypatch.setattr(JobFile, "validate", lambda x: True)
    monkeypatch.setattr(JobFile, "plan", lambda x: "123456")
    monkeypatch.setattr(JobFile, "run", lambda x: True)

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


def test_plan_nomad_job_failed_start(monkeypatch):
    """Test plan_nomad_job when job.run fails."""
    monkeypatch.setattr(JobFile, "validate", lambda x: True)
    monkeypatch.setattr(JobFile, "plan", lambda x: "123456")
    monkeypatch.setattr(JobFile, "run", lambda x: False)

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
