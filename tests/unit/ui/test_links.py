"""Tests for shared web UI link builders."""

from __future__ import annotations

from nd.ui.links import job_url, link, node_url


def test_job_url_targets_jobs_route() -> None:
    """Verify a job link points at the Nomad jobs UI route."""
    # Given a UI base URL and a job id
    # When building the job URL
    url = job_url("http://10.0.30.95:4646", "jackett")
    # Then it targets the jobs route
    assert url == "http://10.0.30.95:4646/ui/jobs/jackett"


def test_node_url_targets_clients_route() -> None:
    """Verify a node link points at the Nomad clients UI route."""
    # When building the node URL
    url = node_url("https://nomad.example.org", "ebd78455")
    # Then it targets the clients route
    assert url == "https://nomad.example.org/ui/clients/ebd78455"


def test_link_wraps_text_in_rich_markup() -> None:
    """Verify link wraps text in Rich hyperlink markup."""
    # When wrapping text in a link
    markup = link("https://nomad.example.org/ui/jobs/web", "web")
    # Then it is Rich link markup pointing at the URL
    assert markup == "[link=https://nomad.example.org/ui/jobs/web]web[/link]"
