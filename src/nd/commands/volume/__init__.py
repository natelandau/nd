"""The ``nd volume`` command: register, delete, and list dynamic host volumes.

Split into pure planning (`report`), Rich rendering (`render`), and Typer wiring plus
async orchestration (`command`).
"""

from nd.commands.volume.command import app

__all__ = ["app"]
