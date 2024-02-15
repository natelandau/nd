"""Constants for the nd package."""

from enum import Enum


class NDObject(Enum):
    """Enum for Nomad Objects."""

    JOBFILE = "jobfile"
    RUNNING_JOB = "running job"
    ALLOCATION = "allocation"
    NODE = "node"
    TASK = "task"
