"""Constants for the nd package."""

from enum import Enum
from pathlib import Path

CONFIG_PATH = Path.home() / ".nd.toml"


class NDObject(Enum):
    """Enum for Nomad Objects."""

    JOBFILE = "jobfile"
    RUNNING_JOB = "running job"
    ALLOCATION = "allocation"
    NODE = "node"
    TASK = "task"
