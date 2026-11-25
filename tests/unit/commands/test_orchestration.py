"""Tests for the shared job-lifecycle command scaffolding."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from nd.commands._orchestration import (
    Outcome,
    Severity,
    confirm_jobs,
    exit_code_for,
    final_panel_title,
    report_outcomes,
    request_all,
)
from nd.nomad import NomadError
from nd.ui.styles import OUTCOME_GLYPH
from tests.helpers import capture_output

if TYPE_CHECKING:
    from tests.conftest import PromptAnswers


def _outcome(name: str, severity: Severity, *, detail: str = "", warnings: str = "") -> Outcome:
    return Outcome(name=name, severity=severity, label="label", detail=detail, warnings=warnings)


@pytest.mark.parametrize("severity", list(Severity))
def test_outcome_row_marks_label_with_its_severity_glyph(severity: Severity):
    """Verify a finished row pairs the severity's glyph with the outcome's own label."""
    # Given an outcome of each severity
    outcome = Outcome(name="web", severity=severity, label="still draining")

    # When building its finished row
    glyph, label = outcome.row()

    # Then the glyph matches the severity and the label text is kept
    assert glyph == OUTCOME_GLYPH[severity]
    assert "still draining" in label


def test_final_panel_title_full_and_partial():
    """Verify the final title counts clean outcomes, with the X-of-N partial form."""
    # Given outcomes where all succeeded, and where only some did
    all_ok = [_outcome("web", Severity.OK), _outcome("api", Severity.OK)]
    mixed = [_outcome("web", Severity.OK), _outcome("api", Severity.WARN)]

    # When building the final titles
    # Then the title reflects the clean count and the partial form
    assert final_panel_title(all_ok, 12.4, verb="Stopped") == "Stopped 2 jobs · 12s"
    assert final_panel_title(mixed, 12.4, verb="Stopped") == "Stopped 1 of 2 jobs · 12s"


@pytest.mark.parametrize(
    ("severities", "expected"),
    [
        ([Severity.OK, Severity.OK], 0),
        ([Severity.OK, Severity.WARN], 1),
        ([Severity.FAIL], 1),
    ],
    ids=["all-ok", "one-warning", "one-failure"],
)
def test_exit_code_for_is_zero_only_when_all_clean(severities: list[Severity], expected: int):
    """Verify the exit code is 0 only when every outcome finished cleanly."""
    # Given outcomes of the given severities
    outcomes = [_outcome(f"job{i}", severity) for i, severity in enumerate(severities)]

    # When computing the exit code
    # Then any warning or failure makes it 1
    assert exit_code_for(outcomes) == expected


def test_report_outcomes_warns_fails_and_surfaces_warnings():
    """Verify report_outcomes emits a warning, an error, and register warnings."""
    # Given a clean, a timed-out, and a failed outcome (the failed one also warns)
    outcomes = [
        _outcome("clean", Severity.OK),
        Outcome(name="slow", severity=Severity.WARN, label="still deploying"),
        _outcome("broken", Severity.FAIL, detail="boom", warnings="deprecated stanza"),
    ]

    console = capture_output()

    # When reporting them
    report_outcomes(outcomes, fail_verb="deploy")
    text = console.export_text()

    # Then the clean outcome is silent, the detail-less warning falls back to its label,
    # and the failure reports with its register warning
    assert "clean" not in text
    assert "slow: still deploying" in text
    assert "broken failed to deploy" in text
    assert "broken: deprecated stanza" in text


def test_report_outcomes_warning_prefers_detail_over_label():
    """Verify a warning shows the outcome detail in place of its label."""
    # Given a timed-out outcome that carries its own detail
    outcomes = [_outcome("slow", Severity.WARN, detail="stop requested, still draining")]

    console = capture_output()

    # When reporting it
    report_outcomes(outcomes, fail_verb="stop")
    text = console.export_text()

    # Then the detail is used, not the label
    assert "slow: stop requested, still draining" in text


def test_request_all_reports_each_target_and_fails_on_any_error():
    """Verify request_all sends every request, reports failures and warnings, and exits 1."""

    # Given one target that succeeds with a warning and one whose request fails
    async def request(name: str) -> str:
        if name == "broken":
            msg = "boom"
            raise NomadError(msg)
        return "deprecated stanza"

    console = capture_output()

    # When requesting both
    exit_code = asyncio.run(
        request_all(
            ["web", "broken"],
            request,
            name_of=str,
            summary_of=lambda count: f"Registered {count} job(s)",
            fail_verb="register",
        )
    )
    text = console.export_text()

    # Then the success, the failure, and the warning are each reported, and it exits 1
    assert exit_code == 1
    assert "Registered 1 job(s)" in text
    assert "broken failed to register" in text
    assert "web: deprecated stanza" in text


@pytest.mark.parametrize("answer", [True, False])
def test_confirm_jobs_returns_the_users_answer(
    interactive_session: PromptAnswers, *, answer: bool
) -> None:
    """Verify confirm_jobs proceeds only when the user answers yes."""
    # Given an interactive session whose user answers the confirmation
    interactive_session.choice = answer

    # When confirming two jobs
    result = asyncio.run(confirm_jobs(["web", "api"], verb="Stop and PURGE", remedy="pass --force"))

    # Then the user's answer is returned
    assert result is answer
