# type: ignore
"""Tests for the list_jobs function."""
from pathlib import Path

import pytest

from nd._commands.utils import job_files


def test_list_job_files():
    """Test list_jobs function."""
    jobs_dir_list = [
        Path("tests/resources/job_files/valid"),
        Path("tests/resources/job_files/invalid"),
    ]

    valid_jobs = job_files.list_job_files(jobs_dir_list)

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
        valid_jobs = job_files.list_job_files(no_jobs_list)

    assert str(exc_info.value) == "No valid job files found in /some/random/path"

    # Test matching pattern
    valid_jobs = job_files.list_job_files(jobs_dir_list, pattern="sonarr")
    assert len(valid_jobs) == 1

    with pytest.raises(AssertionError) as exc_info:
        valid_jobs = job_files.list_job_files(jobs_dir_list, pattern="zzz")

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
