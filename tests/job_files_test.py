# type: ignore
"""Test JobFile class."""

from pathlib import Path

import pytest
import sh
import typer

from nd.models.job_files import JobFile


def test_job_file_1(tmp_path):
    """Test JobFile class.

    GIVEN a valid job
    WHEN the JobFile object is created
    THEN the JobFile object is valid and the name is parsed correctly
    """
    job_file = Path(tmp_path / "job.hcl")
    job_file.write_text(
        """
job "Test_1234" {
    datacenters = ["dc1"]
    type = "service"
    group "group" {
    """
    )

    job = JobFile(job_file, nomad_address="http://localhost:4646")
    assert job.valid is True
    assert job.name == "Test_1234"
    assert job.creates_backup is False


def test_job_file_2(tmp_path):
    """Test JobFile class.

    GIVEN a valid job with create_filesystem
    WHEN the JobFile object is created
    THEN the JobFile object is valid and the name is parsed correctly
    """
    job_file = Path(tmp_path / "job.hcl")
    job_file.write_text(
        """
job "Test_1234" {
    datacenters = ["dc1"]
    type = "service"
    group "group" {
    task "task" {
        driver = "docker"
        config {
        image = "Test_1234"
        }
    }
    }
    create_filesystem = true
}
    """
    )

    job = JobFile(job_file, nomad_address="http://localhost:4646")
    assert job.valid is True
    assert job.name == "Test_1234"
    assert job.creates_backup is True


def test_job_file_3(tmp_path):
    """Test JobFile class.

    GIVEN an invalid job
    WHEN the JobFile object is created
    THEN the JobFile object is invalid
    """
    job_file = Path(tmp_path / "job.hcl")
    job_file.write_text("invalid job 'test' {")
    job = JobFile(job_file, nomad_address="http://localhost:4646")
    assert job.valid is False
    assert not job.name
    assert job.creates_backup is False


def test_job_file_4():
    """Test JobFile class.

    GIVEN two valid jobs with the same path
    WHEN the JobFile objects are compared
    THEN the JobFile objects are equal
    """
    job1 = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    job2 = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    assert job1 == job2


def test_job_file_5(tmp_path):
    """Test JobFile class.

    GIVEN two valid jobs different paths
    WHEN the JobFile objects are compared
    THEN the JobFile objects are not equal
    """
    job_file = Path(tmp_path / "job.hcl")
    job_file.write_text(
        """
job "Test_1234" {
    datacenters = ["dc1"]
    type = "service"
    group "group" {
    """
    )
    job1 = JobFile(job_file, nomad_address="http://localhost:4646")
    job2 = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    assert job1 != job2


def test_job_file_6():
    """Test JobFile class.

    GIVEN a list with two equivalent job files
    WHEN the list is converted to a set
    THEN the set contains only one element based on the hash of the JobFile object
    """
    job1 = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    job2 = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    test_list = [job1, job2]
    assert len(test_list) == 2
    assert len(set(test_list)) == 1


def test_plan_1(mocker):
    """Test plan() method.

    GIVEN a valid job
    WHEN `nomad plan` returns a modify index id
    THEN the a modify index id is returned
    """
    result = """\
+ Job: "example"
+ Task Group: "alloc" (3 create)
  + Task: "alpine" (forces create)

Scheduler dry-run:
- All tasks successfully allocated.

Job Modify Index: 12345678910
To submit the job with version verification run:

nomad job run -check-index 12345678910 tests/fixtures/jobfile_valid.hcl

When running the job with the check-index flag, the job will only be run if the
job modify index given matches the server-side version. If the index has
changed, another user has modified the job and the plan's results are
potentially invalid.
        """
    job = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    mocker.patch("nd.models.job_files.sh.nomad", return_value=result)
    assert job.plan() == "12345678910"


def test_plan_2(mocker):
    """Test plan() method.

    GIVEN a valid job
    WHEN `nomad plan` does not return a modify index id
    THEN None is returned
    """
    result = """\
Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.
        """
    job = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    mocker.patch("nd.models.job_files.sh.nomad", return_value=result)
    assert job.plan() is None


def test_plan_3(mocker):
    """Test plan() method.

    GIVEN a valid job
    WHEN nomad is not installed
    THEN the plan() method exits with an error
    """
    job = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    mocker.patch("nd.models.job_files.sh.nomad", side_effect=sh.CommandNotFound("nomad"))
    with pytest.raises(typer.Exit):
        job.plan()


def test_plan_4(mocker):
    """Test plan() method.

    GIVEN a valid job
    WHEN `nomad plan` returns an error
    THEN None is returned
    """
    job = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    mocker.patch("nd.models.job_files.sh.nomad", side_effect=sh.ErrorReturnCode_1("", b"", b""))
    assert job.plan() is None


def test_validate_1(mocker):
    """Test validate() method.

    GIVEN a valid job
    WHEN `nomad validate` is run
    THEN validate() returns True
    """
    job = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    mocker.patch("nd.models.job_files.sh.nomad", return_value="Job validation successful")
    assert job.validate() is True


def test_validatte_2(mocker):
    """Test plan() method.

    GIVEN a valid job
    WHEN nomad is not installed
    THEN the validate() method exits with an error
    """
    job = JobFile(Path("tests/fixtures/jobfile_valid.hcl"), nomad_address="http://localhost:4646")
    mocker.patch("nd.models.job_files.sh.nomad", side_effect=sh.CommandNotFound("nomad"))
    with pytest.raises(typer.Exit):
        job.validate()


def test_validatte_3(mocker):
    """Test plan() method.

    GIVEN an invalid job
    WHEN `nomad validate` returns a non-zero exit code
    THEN the validate() method returns False
    """
    job = JobFile(Path("tests/fixtures/jobfile_invalid.hcl"), nomad_address="http://localhost:4646")
    mocker.patch("nd.models.job_files.sh.nomad", side_effect=sh.ErrorReturnCode_1("", b"", b""))
    assert job.validate() is False
