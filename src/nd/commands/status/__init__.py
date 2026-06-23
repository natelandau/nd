"""The ``nd status`` command: an at-a-glance Nomad cluster overview.

Split into pure aggregation (`report`), Rich rendering (`render`), and Typer
wiring plus async collection (`command`); this module re-exports the public surface.
"""

from nd.commands.status.command import _collect, app, status
from nd.commands.status.render import render_report
from nd.commands.status.report import (
    Health,
    NodeRow,
    ServerInfo,
    StatusReport,
    build_report,
    correlate_nodes,
)

__all__ = [
    "Health",
    "NodeRow",
    "ServerInfo",
    "StatusReport",
    "_collect",
    "app",
    "build_report",
    "correlate_nodes",
    "render_report",
    "status",
]
