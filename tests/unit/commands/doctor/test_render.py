"""Tests for nd doctor output."""

from __future__ import annotations

from pathlib import Path

from nd.commands.doctor.findings import Finding, FindingSeverity, job_finding
from nd.commands.doctor.render import NO_FINDINGS_MESSAGE, TASK_SEPARATOR, render_findings
from nd.ui.links import WebUi
from tests.helpers import NOMAD_TEST_ADDR, capture_output

_FILES = {
    "audiobookshelf": Path("/home/me/homelab/nomad/audiobookshelf.hcl"),
    "reverse-proxy": Path("/home/me/homelab/nomad/reverse-proxy.hcl"),
}
_FINDINGS = [
    job_finding(
        check="latest-tag",
        severity=FindingSeverity.WARNING,
        job_id="audiobookshelf",
        job_name="audiobookshelf",
        path=("audiobookshelf-group", "audiobookshelf"),
        problem="advplyr/audiobookshelf",
    ),
    job_finding(
        check="latest-tag",
        severity=FindingSeverity.WARNING,
        job_id="reverse-proxy",
        job_name="reverse-proxy",
        path=("reverse-proxy-group", "whoami"),
        problem="containous/whoami",
    ),
    Finding(
        check="unused-volume",
        severity=FindingSeverity.INFO,
        target="volume:music",
        problem="",
        fix_hint="nd volume delete music",
    ),
]


def test_render_findings_puts_each_finding_on_one_line_at_80_columns() -> None:
    """Verify a standard-width terminal shows each finding whole, on a single line."""
    # Given an 80-column terminal
    console = capture_output(width=80)

    # When rendering typical findings
    render_findings(_FINDINGS, file_paths=_FILES, ui=WebUi(NOMAD_TEST_ADDR))

    # Then each finding's subject, detail, and file share one line, and nothing is cut off
    lines = console.export_text().splitlines()
    expected_rows = [
        ("audiobookshelf", "advplyr/audiobookshelf", "audiobookshelf.hcl"),
        (f"reverse-proxy {TASK_SEPARATOR} whoami", "containous/whoami", "reverse-proxy.hcl"),
        ("music", "nd volume delete music", ""),
    ]
    for subject, detail, file_name in expected_rows:
        assert any(subject in line and detail in line and file_name in line for line in lines), (
            f"no single line holds {subject!r}, {detail!r}, and {file_name!r}"
        )
    assert not any("…" in line for line in lines)


def test_render_findings_links_job_to_ui_and_file_to_path() -> None:
    """Verify the job name opens the job in the Nomad UI and the file name opens the file."""
    # Given a job finding with a local file
    console = capture_output(width=120)

    # When rendering it
    render_findings(_FINDINGS[:1], file_paths=_FILES, ui=WebUi(NOMAD_TEST_ADDR))

    # Then the output carries terminal hyperlinks to both
    styled = console.export_text(styles=True)
    assert f"{NOMAD_TEST_ADDR}/ui/jobs/audiobookshelf" in styled
    assert _FILES["audiobookshelf"].as_uri() in styled


def test_render_findings_with_none_reports_success() -> None:
    """Verify an empty result says no problems were found."""
    # Given no findings
    console = capture_output()

    # When rendering them
    render_findings([], file_paths={}, ui=WebUi(NOMAD_TEST_ADDR))

    # Then the output says so
    assert NO_FINDINGS_MESSAGE in console.export_text()


def test_render_findings_names_child_job_once() -> None:
    """Verify a job-level finding on a job whose name holds a slash shows the name alone."""
    # Given a finding on a dispatched child job
    console = capture_output(width=120)
    finding = job_finding(
        check="blocked-eval",
        severity=FindingSeverity.WARNING,
        job_id="backup/dispatch-1-abc",
        job_name="backup/dispatch-1-abc",
        problem="blocked",
    )

    # When rendering it
    render_findings([finding], file_paths={}, ui=WebUi(NOMAD_TEST_ADDR))

    # Then the subject carries no group or task suffix
    assert TASK_SEPARATOR not in console.export_text()
