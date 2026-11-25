"""The ``nd status`` command: an at-a-glance Nomad cluster overview.

Split into pure aggregation (`report`), Rich rendering (`render`), and Typer
wiring plus async collection (`command`).
"""

from nd.commands.status.command import app, status

__all__ = ["app", "status"]
