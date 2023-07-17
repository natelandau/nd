"""Model for Nomad job files."""

import re
from pathlib import Path

import rich.repr
import sh
import typer

from nd.models.nomad_api import NomadAPI
from nd.utils import alerts
from nd.utils.alerts import logger as log
from nd.utils.console import console


@rich.repr.auto
class JobFile:
    """Class defining Nomad job files on the filesystem."""

    def __init__(
        self, path: Path, nomad_address: str, nomad_api: NomadAPI = None, dry_run: bool = False
    ):
        self.api = nomad_api
        self.dry_run = dry_run
        self.index_id = None
        self.nomad_address = nomad_address
        self.path = path
        self.valid, self.name, self.creates_backup = self._parse()

    def __hash__(self) -> int:
        """Hash the JobFile object."""
        return hash(self.path)

    def __eq__(self, other: object) -> bool:
        """Compare two JobFile objects."""
        if not isinstance(other, JobFile):
            return NotImplemented

        return self.path == other.path

    def __rich_repr__(self) -> rich.repr.RichReprResult:  # pragma: no cover
        """Rich representation of the JobFile object."""
        yield "creates_backup", self.creates_backup
        yield "dry_run", self.dry_run
        yield "name", self.name
        yield "nomad_address", self.nomad_address
        yield "path", self.path
        yield "valid", self.valid

    def _parse(self) -> tuple[bool, str, bool]:
        """Parse the job file.

        Returns:
            tuple[bool, str, bool]: Tuple of (valid, name, creates_backup)
        """
        content = self.path.read_text()
        valid = False
        name = ""
        creates_backup = False
        for line in content.splitlines():
            if re.match(r'^job +["\'][-\w]+["\'] +\{', line, re.IGNORECASE):
                valid = True
                name = re.sub(r'^job +["\']([-\w]+)["\'].*', r"\1", line, flags=re.IGNORECASE)
                if re.search(r".*create_filesystem.*", content, re.IGNORECASE):
                    creates_backup = True
                break

        return valid, name, creates_backup

    def plan(self) -> str | None:
        """Plan Nomad job using 'nomad plan [job]' and returns the modify-index number to be used with 'nomad job run'.

        Returns:
            str | None: The modify-index value if the job file is valid, None otherwise.

        Raises:
            typer.Exit: If the Nomad binary is not found.
        """
        try:
            output = sh.nomad(
                "job",
                "plan",
                f"-address={self.nomad_address}",
                "-no-color",
                self.path,
                _ok_code=[0, 1],
            )
        except sh.CommandNotFound as e:
            log.error("Nomad binary not found. Please install Nomad.")
            raise typer.Exit(1) from e
        except sh.ErrorReturnCode as e:
            log.error(f"Failed to plan job file {self.path}: {e}")
            return None

        try:
            if modify_index := re.search(r"^Job Modify Index: (\d+)$", output, re.MULTILINE).group(
                1
            ):
                log.trace(f"{self.path} planned with modify index: {modify_index}")
                return modify_index
        except AttributeError:
            alerts.notice(f"Failed to parse job plan output for {self.path}")

        return None

    def run(self) -> bool:
        """Run the job file."""
        if not self.valid or not self.validate():
            alerts.notice(f"Job file {self.path} is not valid")
            return False

        if self.dry_run:
            alerts.dryrun(f"Would run job file {self.path}")
            return True

        with console.status(
            f"Starting {self.name}...",
            spinner="bouncingBall",
        ):
            if index_id := self.plan():
                try:
                    sh.nomad(
                        "job",
                        "run",
                        "-no-color",
                        "-check-index",
                        index_id,
                        self.path,
                    )
                except sh.CommandNotFound as e:
                    log.error("Nomad binary not found. Please install Nomad.")
                    raise typer.Exit(1) from e
                except sh.ErrorReturnCode as e:
                    log.error(f"Failed to run job file {self.path}: {e}")
                    return False
                return True

        return False

    def validate(self) -> bool:
        """Validate the job file.

        Returns:
            bool: True if the job file is valid, False otherwise.

        Raises:
            typer.Exit: If the Nomad binary is not found.
        """
        try:
            sh.nomad(
                "job", "validate", f"-address={self.nomad_address}", "-no-color", str(self.path)
            )
        except sh.CommandNotFound as e:
            log.error("Nomad binary not found. Please install Nomad.")
            raise typer.Exit(1) from e
        except sh.ErrorReturnCode as e:
            log.error(f"Failed to validate job file {self.path}: {e}")
            return False
        return True
