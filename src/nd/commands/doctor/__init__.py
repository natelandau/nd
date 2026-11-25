"""The ``nd doctor`` command: list common job and cluster problems.

Split into the snapshot fetch (`snapshot`), pure checks (`job_checks`, `cluster_checks`,
registered in `checks`), Rich output (`render`), and Typer wiring (`command`).
"""

from nd.commands.doctor.command import app, doctor

__all__ = ["app", "doctor"]
