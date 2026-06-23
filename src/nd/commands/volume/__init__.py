"""The ``nd volume`` command: register, delete, and list dynamic host volumes.

Split into pure planning (`report`), Rich rendering (`render`), and Typer wiring plus
async orchestration (`command`); this module re-exports the public surface.
"""

from nd.commands.volume.command import app
from nd.commands.volume.report import (
    Registration,
    VolumeRow,
    build_list_rows,
    build_register_payload,
    plan_deletions,
    plan_registrations,
)

__all__ = [
    "Registration",
    "VolumeRow",
    "app",
    "build_list_rows",
    "build_register_payload",
    "plan_deletions",
    "plan_registrations",
]
