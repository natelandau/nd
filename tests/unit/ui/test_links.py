"""Tests for the WebUi hyperlink builder."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nd.ui.links import WebUi, file_link

if TYPE_CHECKING:
    import pytest


def test_webui_job_links_jobs_route() -> None:
    """Verify a job link points at the Nomad jobs UI route and wraps the label."""
    # Given a WebUi bound to a base URL
    web = WebUi("http://10.0.30.95:4646")

    # When building a job link
    markup = web.job(job_id="jackett", label="Jackett")

    # Then it is Rich link markup targeting the jobs route
    assert markup == "[link=http://10.0.30.95:4646/ui/jobs/jackett]Jackett[/link]"


def test_webui_node_links_clients_route() -> None:
    """Verify a node link points at the Nomad clients UI route and wraps the label."""
    # Given a WebUi bound to a base URL
    web = WebUi("https://nomad.example.org")

    # When building a node link
    markup = web.node(node_id="ebd78455", label="worker-1")

    # Then it is Rich link markup targeting the clients route
    assert markup == "[link=https://nomad.example.org/ui/clients/ebd78455]worker-1[/link]"


def test_file_link_resolves_relative_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a relative job file path links to its absolute file URI."""
    # Given a working directory and a path relative to it
    monkeypatch.chdir(tmp_path)

    # When building a file link
    markup = file_link(Path("jobs/web.hcl"), "web.hcl")

    # Then it links to the absolute file
    assert markup == f"[link={(tmp_path / 'jobs/web.hcl').as_uri()}]web.hcl[/link]"
