"""Shared utility functions for working with Nomad job files."""

import re

# import nd._commands.utils.shared as shared
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
        command = ["nomad", "job", "validate", str(self.file)]
        log.trace(f"Running command: {' '.join(command)}")
        try:
            process = subprocess.Popen(  # nosec
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            )
        except FileNotFoundError:  # pragma: no cover
            log.error("Nomad binary not found. Please install Nomad.")
            raise sys.exit(1)

        while True:
            # output = process.stdout.readline()  # type: ignore [union-attr]
            return_code = process.poll()
            if return_code is not None:
                if return_code == 0:
                    log.debug(f"Nomad validated job file: {self.file}")
                    return True
                else:
                    # for output in process.stdout.readlines():  # type: ignore [union-attr]
                    #     log.trace(output.strip())
                    log.debug(f"Nomad job validation failed for '{self.file}'")
                    return False


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
def list_job_files(directories: list[Path | str]) -> list[JobFile]:
    """
    Lists valid Nomad job files within a specified directory.

    Args:
        directories: Path to directory to search for job files

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
                if job_file is not None:
                    valid_job_files.append(job_file)

    for idx, job in enumerate(valid_job_files):
        if not job.validate():
            valid_job_files.pop(idx)

    assert (
        len(valid_job_files) > 0
    ), f"No valid job files found in {', '.join(map(str, directories))}"
    return valid_job_files
