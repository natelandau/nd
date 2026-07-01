"""Tests for the shared job-lifecycle command scaffolding."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from nclutils import pp
from rich.console import Console

from nd.commands._orchestration import (
    confirm_jobs,
    fail_row,
    final_panel_title,
    ok_row,
    report_outcomes,
    warn_row,
)
from nd.ui.styles import OUTCOME_GLYPH


@dataclass(frozen=True)
class _Outcome:
    """A minimal outcome stand-in for exercising the shared reporters."""

    name: str
    kind: str  # "ok", "warn", or "fail"
    detail: str = ""
    warnings: str = ""


def _capture(func) -> str:
    """Run ``func`` under a recording emitter and return the captured text."""
    console = Console(theme=pp.THEME, record=True, force_terminal=True, width=100)
    emitter = pp.Emitter(console=console, err_console=console)
    original = pp.get_default()
    pp.set_default(emitter)
    try:
        func()
    finally:
        pp.set_default(original)
    return console.export_text()


def test_row_helpers_pair_glyph_and_colored_label():
    """Verify the row helpers pair each glyph with its matching color and label."""
    # When building a row of each severity
    # Then each carries its glyph and a same-colored label
    assert ok_row("stopped") == (OUTCOME_GLYPH["ok"], "[green]stopped[/]")
    assert warn_row("still draining") == (OUTCOME_GLYPH["warn"], "[yellow]still draining[/]")
    assert fail_row("failed") == (OUTCOME_GLYPH["fail"], "[red]failed[/]")


def test_final_panel_title_full_and_partial():
    """Verify the final title shows totals, elapsed, and the X-of-N partial form."""
    # Given a set of outcomes where only some succeeded
    outcomes = [
        _Outcome("web", "ok"),
        _Outcome("api", "warn"),
    ]
    succeeded = lambda o: o.kind == "ok"  # noqa: E731

    # When all succeed vs only some
    all_ok = [_Outcome("web", "ok"), _Outcome("api", "ok")]

    # Then the title reflects the clean count and the partial form
    assert final_panel_title(all_ok, 12.4, verb="Stopped", succeeded=succeeded) == (
        "Stopped 2 jobs · 12s"
    )
    assert final_panel_title(outcomes, 12.4, verb="Stopped", succeeded=succeeded) == (
        "Stopped 1 of 2 jobs · 12s"
    )


def test_report_outcomes_warns_fails_and_surfaces_warnings():
    """Verify report_outcomes emits a warning, an error, and register warnings."""
    # Given a clean, a timed-out, and a failed outcome (the failed one also warns)
    outcomes = [
        _Outcome("clean", "ok"),
        _Outcome("slow", "warn"),
        _Outcome("broken", "fail", detail="boom", warnings="deprecated stanza"),
    ]

    # When reporting them
    text = _capture(
        lambda: report_outcomes(
            outcomes,
            name_of=lambda o: o.name,
            detail_of=lambda o: o.detail,
            is_warn=lambda o: o.kind == "warn",
            is_fail=lambda o: o.kind == "fail",
            fail_verb="deploy",
            warn_fallback="still deploying",
            warnings_of=lambda o: o.warnings,
        )
    )

    # Then the clean outcome is silent, the timeout falls back, and the failure reports
    assert "clean" not in text
    assert "slow: still deploying" in text
    assert "broken failed to deploy" in text
    assert "broken: deprecated stanza" in text


def test_report_outcomes_warn_fallback_uses_detail_when_present():
    """Verify a warning shows the outcome detail in place of the fallback."""
    # Given a timed-out outcome that carries its own detail
    outcomes = [_Outcome("slow", "warn", detail="stop requested, still draining")]

    # When reporting with no warnings accessor
    text = _capture(
        lambda: report_outcomes(
            outcomes,
            name_of=lambda o: o.name,
            detail_of=lambda o: o.detail,
            is_warn=lambda o: o.kind == "warn",
            is_fail=lambda o: o.kind == "fail",
            fail_verb="stop",
        )
    )

    # Then the detail is used, not the fallback
    assert "slow: stop requested, still draining" in text


def test_confirm_jobs_builds_prompt_and_coerces_answer(monkeypatch):
    """Verify confirm_jobs renders the verb and names and returns a bool."""
    # Given a stubbed prompt that records its message and returns the chosen value
    seen: dict[str, str] = {}

    def fake_select_one(choices, message):  # noqa: ANN202
        seen["message"] = message

        async def _answer():  # noqa: ANN202
            return True

        return _answer()

    monkeypatch.setattr("nd.commands._orchestration.select_one", fake_select_one)

    # When confirming two jobs
    result = asyncio.run(confirm_jobs(["web", "api"], verb="Stop and PURGE"))

    # Then the prompt reads the shared wording and the answer is a bool
    assert result is True
    assert seen["message"] == "Stop and PURGE 2 job(s): web, api?"
