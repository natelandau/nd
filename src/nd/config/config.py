"""Instantiate Configuration class and set default values."""

import shutil
from pathlib import Path
from typing import Any

import rich.repr
import typer
import validators

from nd.utils import alerts
from nd.utils.alerts import logger as log

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore [no-redef]

PATH_CONFIG_DEFAULT = Path(__file__).parent / "default_config.toml"


@rich.repr.auto
class Config:
    """Representation of a configuration file."""

    def __init__(
        self,
        config_path: Path = None,
        context: dict[str, Any] = {},
    ) -> None:
        """Initialize configuration file."""
        self.config_path = config_path.expanduser().resolve() if config_path else None
        self.context = context
        self.dry_run = self.context["dry_run"] if "dry_run" in self.context else False
        self.force = self.context["force"] if "force" in self.context else False

        if not config_path or not self.config_path.exists():
            self._create_config()

        self.config = self._load_config()
        self.file_ignore_strings = self.config["file_ignore_strings"]
        self.job_file_locations = self.config["job_file_locations"]
        self.nomad_address = self.config["nomad_address"]

    def __rich_repr__(self) -> rich.repr.Result:  # pragma: no cover
        """Return the representation of the configuration file."""
        yield "nomad_address", self.nomad_address
        yield "config_path", self.config_path
        yield "file_ignore_strings", self.file_ignore_strings
        yield "config", self.config
        yield "context", self.context
        yield "dry_run", self.dry_run
        yield "force", self.force
        yield "job_file_locations", self.job_file_locations

    def _create_config(self) -> None:
        """Create a configuration file from the default when it does not exist."""
        if self.config_path is None:
            log.error("No configuration file specified")
            raise typer.Exit(code=1)

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(PATH_CONFIG_DEFAULT, self.config_path)
        alerts.success(f"Created default configuration file at {self.config_path}")
        alerts.notice(f"Please edit {self.config_path} before continuing")
        raise typer.Exit(code=1)

    def _load_config(self) -> dict[str, Any]:
        """Load the configuration file."""
        log.debug(f"Loading configuration from {self.config_path}")
        with self.config_path.open("rb") as f:
            try:
                config = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                log.exception(f"Could not parse '{self.config_path}'")
                raise typer.Exit(code=1) from e

        if config == {}:
            log.error(f"Configuration file '{self.config_path}' is empty or malformed")
            raise typer.Exit(code=1)

        if "nomad_address" not in config or not validators.url(config["nomad_address"]):
            log.error(
                "Configuration file 'nomad_address' is not a valid URL. "
                "Please check your configuration file."
            )
            raise typer.Exit(code=1)

        if "job_file_locations" not in config or not isinstance(config["job_file_locations"], list):
            log.error(
                "Configuration file 'job_file_locations' is not a list. "
                "Please check your configuration file."
            )
            raise typer.Exit(code=1)

        if "file_ignore_strings" not in config or not isinstance(
            config["file_ignore_strings"], list
        ):
            config["file_ignore_strings"] = []

        return config
