"""Shared builders for Rich hyperlinks into the Nomad web UI."""

from __future__ import annotations


def link(url: str, text: str) -> str:
    """Wrap text in Rich link markup pointing at the given URL."""
    return f"[link={url}]{text}[/link]"


def job_url(ui_base: str, job_id: str) -> str:
    """Build the web UI URL for a job."""
    return f"{ui_base}/ui/jobs/{job_id}"


def node_url(ui_base: str, node_id: str) -> str:
    """Build the web UI URL for a client node."""
    return f"{ui_base}/ui/clients/{node_id}"
