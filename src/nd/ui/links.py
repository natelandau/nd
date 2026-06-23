"""Rich hyperlinks into the Nomad web UI."""

from __future__ import annotations


class WebUi:
    """Builds Rich hyperlinks into the Nomad web UI for one base URL.

    Bind it to a base URL (``NomadConfig.ui_base``) once, then build job and node
    links by id without re-threading the base through every call site.
    """

    def __init__(self, base: str) -> None:
        self._base = base

    def job(self, job_id: str, label: str) -> str:
        """Wrap ``label`` in a Rich link to the job's web UI page."""
        return f"[link={self._base}/ui/jobs/{job_id}]{label}[/link]"

    def node(self, node_id: str, label: str) -> str:
        """Wrap ``label`` in a Rich link to the client node's web UI page."""
        return f"[link={self._base}/ui/clients/{node_id}]{label}[/link]"
