# type: ignore
"""Tests for the list_jobs function."""
import subprocess
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from nd._commands.utils import job_files
from nd._commands.utils.job_files import JobFile


def test_validate(monkeypatch):
    """Test validate() method of JobFile."""
    result_true = CompletedProcess(
        args=[
            "nomad",
            "job",
            "validate",
            "-no-color",
            "/at/some/path/job.hcl",
        ],
        returncode=0,
        stdout="",
        stderr="",
    )
    result_false = CompletedProcess(
        args=[
            "nomad",
            "job",
            "validate",
            "-no-color",
            "/at/some/path/job.hcl",
        ],
        returncode=1,
        stdout="",
        stderr="Error getting job struct: Error parsing job file from tests/resources/job_files/invalid/template-groups.hcl:\ntemplate-groups.hcl:67,70-71: Invalid expression; Expected the start of an expression, but found an invalid expression token.\n",
    )
    job = JobFile(
        name="sonarr", file=Path("tests/resources/job_files/valid/sonarr.hcl"), local_backup=False
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result_true)
    assert job.validate() is True

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result_false)
    assert job.validate() is False


def test_plan(monkeypatch):
    """Test plan() method of JobFile."""
    result1 = CompletedProcess(
        args=[
            "nomad",
            "job",
            "plan",
            "-no-color",
            "-diff=false",
            "/at/some/path/job.hcl",
        ],
        returncode=0,
        stdout="Scheduler dry-run:\n- All tasks successfully allocated.\n\nJob Modify Index: 772785\nTo submit the job with version verification run:\n\nnomad job run -check-index 772785 tests/resources/job_files/valid/sonarr.hcl\n\nWhen running the job with the check-index flag, the job will only be run if the\njob modify index given matches the server-side version. If the index has\nchanged, another user has modified the job and the plan's results are\npotentially invalid.\n",
        stderr="",
    )
    result2 = CompletedProcess(
        args=[
            "nomad",
            "job",
            "plan",
            "-no-color",
            "-diff=false",
            "/at/some/path/job.hcl",
        ],
        returncode=0,
        stdout="Scheduler dry-run:\n- All tasks successfully allocated.\n\n\nTo submit the job with version verification run:\n\nnomad job run -check-index tests/resources/job_files/valid/sonarr.hcl\n\nWhen running the job with the check-index flag, the job will only be run if the\njob modify index given matches the server-side version. If the index has\nchanged, another user has modified the job and the plan's results are\npotentially invalid.\n",
        stderr="",
    )
    result3 = CompletedProcess(
        args=[
            "nomad",
            "job",
            "plan",
            "-no-color",
            "-diff=false",
            "/at/some/path/job.hcl",
        ],
        returncode=1,
        stdout="Scheduler dry-run:\n- All tasks successfully allocated.\n\nJob Modify Index: 772785\nTo submit the job with version verification run:\n\nnomad job run -check-index 772785 tests/resources/job_files/valid/sonarr.hcl\n\nWhen running the job with the check-index flag, the job will only be run if the\njob modify index given matches the server-side version. If the index has\nchanged, another user has modified the job and the plan's results are\npotentially invalid.\n",
        stderr="",
    )
    job = JobFile(
        name="sonarr", file=Path("tests/resources/job_files/valid/sonarr.hcl"), local_backup=False
    )
    monkeypatch.setattr(job, "validate", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result1)
    result = job.plan()
    assert result == "772785"

    # Assert plan() exits if job is not valid
    monkeypatch.setattr(job, "validate", lambda: False)
    with pytest.raises(SystemExit) as exc_info:
        job.plan()
    assert exc_info.value.code == 1

    # Assert plan exits if modify_index is not found
    monkeypatch.setattr(job, "validate", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result2)
    with pytest.raises(SystemExit) as exc_info:
        job.plan()
    assert exc_info.value.code == 1

    # Assert plan exits if nomad plan returns non-zero exit code
    monkeypatch.setattr(job, "validate", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result3)
    with pytest.raises(SystemExit) as exc_info:
        job.plan()
    assert exc_info.value.code == 1


def test_list_valid_jobs():
    """Test list_jobs function."""
    jobs_dir_list = [
        Path("tests/resources/job_files/valid"),
        Path("tests/resources/job_files/invalid"),
    ]

    valid_jobs = job_files.list_valid_jobs(jobs_dir_list)

    assert len(valid_jobs) == 4

    job_names = []
    for job in valid_jobs:
        job_names.append(job.name)

    assert "sonarr" in job_names
    assert "lidarr" in job_names
    assert "whoogle" in job_names
    assert "template-simple" in job_names
    assert "template-group" not in job_names

    # Test no jobs found
    no_jobs_list = [Path("/some/random/path")]
    with pytest.raises(AssertionError) as exc_info:
        valid_jobs = job_files.list_valid_jobs(no_jobs_list)

    assert str(exc_info.value) == "No valid job files found in /some/random/path"

    # Test matching pattern
    valid_jobs = job_files.list_valid_jobs(jobs_dir_list, pattern="sonarr")
    assert len(valid_jobs) == 1

    with pytest.raises(AssertionError) as exc_info:
        valid_jobs = job_files.list_valid_jobs(jobs_dir_list, pattern="zzz")

    # Test failed matching pattern
    assert (
        str(exc_info.value)
        == "No valid job files found in tests/resources/job_files/valid, tests/resources/job_files/invalid matching 'zzz'"
    )


def test_parse_job_file():
    """Test parse_job_file function."""
    job = job_files.parse_job_file(Path("tests/resources/job_files/valid/sonarr.hcl"))
    assert job.name == "sonarr"
    assert job.file == Path("tests/resources/job_files/valid/sonarr.hcl")
    assert job.local_backup is True

    job = job_files.parse_job_file(Path("tests/resources/job_files/valid/whoogle.hcl"))
    assert job.name == "whoogle"
    assert job.file == Path("tests/resources/job_files/valid/whoogle.hcl")
    assert job.local_backup is False

    job2 = job_files.parse_job_file(Path("tests/resources/job_files/invalid/nojob.hcl"))
    assert job2 is None
