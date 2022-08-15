"""Shared utility functions for working with Nomad job files."""

import re
import subprocess
import sys
from pathlib import Path

import rich.repr

from nd._commands.utils.alerts import logger as log


@rich.repr.auto
class JobFile:
    """Class defining Nomad job files on the filesystem.

    Methods:
        plan() - Plan a job
        validate() - Validate a job
        run() - Run a job
    """

    def __init__(
        self, name: str = "", file: Path = Path("/dev/null"), local_backup: bool = False
    ) -> None:
        self.name: str = name
        self.file: Path = file
        self.directory: Path = file.parent
        self.local_backup: bool = local_backup

    @log.catch
    def validate(self) -> bool:
        """
        Validate a nomad job file using 'nomad validate [job]'.

        Returns:
            True if validation is successful
            False if validation is not successful

        Raises:
            exit: If Nomad binary is not installed on the system

        Usage:
            if job.validate():
                do something
        """
        command = ["nomad", "job", "validate", "-no-color", str(self.file)]
        log.trace(f"Running command: {' '.join(command)}")

        try:
            result = subprocess.run(command, capture_output=True, text=True)  # nosec
        except FileNotFoundError:  # pragma: no cover
            print("Nomad binary not found. Please install Nomad.")
            raise sys.exit(1)

        if result.returncode == 0:
            log.debug(f"Nomad validated job file: {self.file}")
            return True
        else:
            log.debug(f"Error from 'nomad job validate {self.file}:\n{result.stderr}")
            return False

    @log.catch
    def plan(self) -> str:
        """
        Plan Nomad job using 'nomad plan [job]' and returns the modify-index number to be used with 'nomad job run'.

        Returns:
            Nomad modify-index ID

        Raises:
            exit: If job file is not valid
            exit: If Nomad binary is not installed on the system

        Usage:
            modify_index = job.plan()

        """
        if not self.validate():
            log.error(f"Nomad job file is not valid: {self.file}")
            raise sys.exit(1)

        command = ["nomad", "job", "plan", "-no-color", "-diff=false", str(self.file)]
        log.trace(f"Running command: {' '.join(command)}")

        try:
            result = subprocess.run(command, capture_output=True, text=True)  # nosec
        except FileNotFoundError:  # pragma: no cover
            print("Nomad binary not found. Please install Nomad.")
            raise sys.exit(1)

        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if re.match(r"^Job Modify Index: (\d+)$", line):
                    modify_index = re.match(r"^Job Modify Index: (\d+)$", line).group(1)  # type: ignore [union-attr]
                    break

            try:
                log.debug(f"Planned Nomad job with modify index #: {modify_index}")
                return modify_index
            except NameError:
                log.error("No modify_index")
                raise sys.exit(1)
        else:
            log.error(
                f"Nomad job plan failed for '{self.name}' with return code: {result.returncode}"
            )
            raise sys.exit(1)


@log.catch
def parse_job_file(job_file: Path) -> JobFile | None:
    """
    Parse a Nomad job file and return a JobFile object.

    Args:
        job_file: Path to Nomad job file

    Returns:
        JobFile object
    """
    with job_file.open(mode="r") as file:
        creates_backup = False
        head = [next(file) for x in range(2)]
        for line in head:
            if re.match(r'^job +".*" +\{', line, re.IGNORECASE):
                for line in file:
                    if re.match(r".*create_filesystem.*", line, re.IGNORECASE):
                        creates_backup = True
                        break
                return JobFile(
                    name=job_file.stem,
                    file=job_file,
                    local_backup=creates_backup,
                )

        return None


@log.catch(exclude=AssertionError)
def list_job_files(directories: list[Path | str], pattern: str | None = None) -> list[JobFile]:
    """
    Lists valid Nomad job files within a specified directory.

    Args:
        directories: Path to directory to search for job files
        pattern: Returned job files will match this string

    Returns:
        List of JobFile class objects for valid Nomad jobs

    Raises:
        AssertionError: If no valid job files are found
    """
    valid_job_files = []

    for directory in directories:

        directory = Path(directory)
        if not directory.is_dir():
            continue
        else:
            files = [
                f
                for f in directory.rglob("*")
                if f.is_file() and (f.suffix == ".nomad" or f.suffix == ".hcl")
            ]
            for f in files:
                job_file = parse_job_file(f)
                if (
                    job_file is not None
                    and job_file.validate()
                    and (pattern is None or pattern.lower() in job_file.name.lower())
                ):
                    valid_job_files.append(job_file)

    if pattern is None:
        assert (
            len(valid_job_files) > 0
        ), f"No valid job files found in {', '.join(map(str, directories))}"
    else:
        assert (
            len(valid_job_files) > 0
        ), f"No valid job files found in {', '.join(map(str, directories))} matching '{pattern}'"

    return valid_job_files
