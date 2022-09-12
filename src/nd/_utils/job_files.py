"""Shared utility functions for working with Nomad job files."""

import re
import subprocess
import sys
from pathlib import Path

import rich.repr
from plumbum import FG, CommandNotFound, ProcessExecutionError, local
from rich import print
from rich.prompt import Prompt

from nd._utils import alerts, populate_running_jobs
from nd._utils.alerts import logger as log


@rich.repr.auto
class JobFile:
    """Class defining Nomad job files on the filesystem.

    Attributes:
        name (str): The name of the job file.
        file (Path): The path to the job file.
        directory (Path): The directory containing the job file.
        local_backup (bool): Whether or not the job creates backup the job file on the local filesystem.
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
        """Validate a nomad job file using 'nomad validate [job]'.

        Returns:
            bool: Whether or not the job file is valid.


        Raises:
            exit: If Nomad binary is not installed on the system

        Examples:
            Usage as a validator:

                if job.validate():
                    do something
        """
        command = ["nomad", "job", "validate", "-no-color", str(self.file)]
        log.trace(f"Running command: {' '.join(command)}")

        try:
            result = subprocess.run(command, capture_output=True, text=True)  # nosec
        except FileNotFoundError as e:  # pragma: no cover
            print("Nomad binary not found. Please install Nomad.")
            raise sys.exit(1) from e

        if result.returncode == 0:
            log.debug(f"Nomad validated job file: {self.file}")
            return True
        else:
            log.debug(f"Error from 'nomad job validate {self.file}:\n{result.stderr}")
            return False

    @log.catch
    def plan(self) -> str:
        """Plan Nomad job using 'nomad plan [job]' and returns the modify-index number to be used with 'nomad job run'.

        Returns:
            str: The modify-index number to be used with 'nomad job run'.

        Raises:
            exit: If job file is not valid
            exit: If Nomad binary is not installed on the system

        Usage:
            Grab the modify index from the job file:

                modify_index = job.plan()

        """
        if not self.validate():
            log.error(f"Nomad job file is not valid: {self.file}")
            raise sys.exit(1)

        command = ["nomad", "job", "plan", "-no-color", "-diff=false", str(self.file)]
        log.trace(f"Running command: {' '.join(command)}")

        try:
            result = subprocess.run(command, capture_output=True, text=True)  # nosec
        except FileNotFoundError as e:  # pragma: no cover
            print("Nomad binary not found. Please install Nomad.")
            raise sys.exit(1) from e

        if result.returncode <= 1:
            for line in result.stdout.splitlines():
                if re.match(r"^Job Modify Index: (\d+)$", line):
                    modify_index = re.match(r"^Job Modify Index: (\d+)$", line).group(1)  # type: ignore [union-attr]
                    break

            try:
                log.debug(f"Planned Nomad job with modify index #: {modify_index}")
            except NameError as e:
                log.exception("No modify_index")
                raise sys.exit(1) from e
            else:
                return modify_index
        else:
            log.error(
                f"Nomad job plan failed for '{self.name}' with return code: '{result.returncode}'\n{result.stderr}"
            )
            raise sys.exit(1)

    @log.catch
    def run(self) -> bool:
        """Run a Nomad job.

        Returns:
            bool: Whether or not the job was successfully run.
        """
        modify_index = self.plan()
        if modify_index != "0":
            print(f"'{self.name}' is already running.  New modify index: '{modify_index}'")
            confirm = Prompt.ask("'Do you want run a new version?", choices=["y", "n"])
            if confirm == "n":
                print(f"{self.name}: Run aborted")
                return False

        try:
            nomad = local["nomad"]
            nomad["job", "run", "-check-index", modify_index, str(self.file)] & FG
        except CommandNotFound:
            log.error("Nomad binary is not installed")  # noqa: TC400
            return False
        except ProcessExecutionError as e:
            alerts.error(f"Nomad job plan failed for '{self.name}'.\n{e}")  # noqa: TC400
            return False
        else:
            return True


@log.catch
def parse_job_file(job_file: Path) -> JobFile | None:
    """Parse a Nomad job file and return a JobFile object.

    Args:
        job_file: Path to Nomad job file

    Returns:
        JobFile: JobFile object if job file is valid, None otherwise.
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
def list_valid_jobs(
    directories: list[Path | str],
    pattern: str | None = None,
    filter_running: bool = False,
    config: dict = {},
) -> list[JobFile]:
    """Lists valid Nomad job files within a specified directory.

    Args:
        directories: List of directories to search for job files.
        pattern: Optional regex pattern to match job files against.
        filter_running: Whether or not to filter out running jobs.
        config: Dictionary of config values.

    Returns:
        list[JobFile]: List of valid job files

    Raises:
        AssertionError: If no valid job files are found
    """
    valid_job_files = []

    running_job_names = []
    if filter_running:
        for running_job in populate_running_jobs(config["nomad_api_url"]):
            running_job_names.append(running_job.job_id)

    for directory in directories:

        directory = Path(directory).expanduser()
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
                    and (not filter_running or job_file.name not in running_job_names)
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
