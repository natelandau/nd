"""Instantiate Configuration class and set default values."""

from typing import Annotated, ClassVar

import validators
from confz import BaseConfig, CLArgSource, ConfigSources, FileSource
from pydantic import BeforeValidator, field_validator

from nd.constants import CONFIG_PATH


def pass_opt_without_value(value: str) -> bool:
    """Confz does not work well with Typer options. Confz requires a value for each CLI option, but Typer does not. To workaround this, for example, if --log-to-file is passed, we set the value to "True" regardless of what follows the CLI option."""
    if value:
        return True

    return False


OPT_BOOLEAN = Annotated[
    bool,
    BeforeValidator(pass_opt_without_value),
]


class NDConfig(BaseConfig):  # type: ignore [misc]
    """Configuration class for nd."""

    file_ignore_strings: tuple[str, ...] = ()
    job_file_locations: tuple[str, ...] = ()
    nomad_address: str = "http://localhost:4646"
    force: OPT_BOOLEAN = False
    dry_run: OPT_BOOLEAN = False

    CONFIG_SOURCES: ClassVar[ConfigSources | None] = [
        FileSource(file=CONFIG_PATH),
        CLArgSource(remap={"dry-run": "dry_run"}),
    ]

    @field_validator("nomad_address")
    @classmethod
    def nomad_address_must_be_valid_url(cls, v: str) -> str:
        """Validate that the nomad address is a valid URL."""
        if not validators.url(v):
            msg = f"{v} is not a valid URL"
            raise ValueError(msg)

        return v
