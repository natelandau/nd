"""Tests for the WebUi hyperlink builder."""

from __future__ import annotations

from nd.ui.links import WebUi


def test_job_link_targets_jobs_route_and_wraps_label() -> None:
    """Verify a job link points at the Nomad jobs UI route and wraps the label."""
    # Given a WebUi bound to a base URL
    web = WebUi("http://10.0.30.95:4646")

    # When building a job link
    markup = web.job("jackett", "Jackett")

    # Then it is Rich link markup targeting the jobs route
    assert markup == "[link=http://10.0.30.95:4646/ui/jobs/jackett]Jackett[/link]"


def test_node_link_targets_clients_route_and_wraps_label() -> None:
    """Verify a node link points at the Nomad clients UI route and wraps the label."""
    # Given a WebUi bound to a base URL
    web = WebUi("https://nomad.example.org")

    # When building a node link
    markup = web.node("ebd78455", "worker-1")

    # Then it is Rich link markup targeting the clients route
    assert markup == "[link=https://nomad.example.org/ui/clients/ebd78455]worker-1[/link]"
