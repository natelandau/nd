"""Tests for shared UI status styles."""

from __future__ import annotations

from nd.ui.styles import OUTCOME_GLYPH, STATUS_STYLE, accent, muted, status_cell


def test_status_cell_known_status() -> None:
    """Verify a known healthy status renders a green check glyph and label."""
    # Given / When
    cell = status_cell("running")
    # Then
    assert cell == "[green]✓ running[/]"


def test_status_cell_unknown_status() -> None:
    """Verify an unknown status falls back to a neutral bullet glyph."""
    # When
    cell = status_cell("mystery")
    # Then
    assert cell == "[default]• mystery[/]"


def test_status_cell_stopping_terminal_reads_stopped() -> None:
    """Verify a terminal allocation renders green "stopped" while stopping."""
    assert status_cell("complete", stopping=True) == "[green]✓ stopped[/]"


def test_status_cell_stopping_transitional_is_yellow() -> None:
    """Verify a not-yet-stopped state (e.g. running) reads yellow while stopping."""
    assert status_cell("running", stopping=True) == "[yellow]• running[/]"
    assert status_cell("pending", stopping=True) == "[yellow]• pending[/]"


def test_status_cell_stopping_failure_stays_red() -> None:
    """Verify a genuine failure stays red while stopping instead of blending to yellow."""
    assert status_cell("failed", stopping=True) == "[red]✗ failed[/]"
    assert status_cell("lost", stopping=True) == "[red]✗ lost[/]"


def test_status_style_covers_failed() -> None:
    """Verify failed-like statuses map to red."""
    assert STATUS_STYLE["failed"] == "red"
    assert STATUS_STYLE["dead"] == "red"


def test_outcome_glyphs_present() -> None:
    """Verify the three outcome glyphs exist with expected colors."""
    assert OUTCOME_GLYPH["ok"] == "[green]✓[/]"
    assert OUTCOME_GLYPH["warn"] == "[yellow]⚠[/]"
    assert OUTCOME_GLYPH["fail"] == "[red]✗[/]"


def test_accent_and_muted_wrap_text() -> None:
    """Verify accent styles identifiers cyan and muted dims secondary text."""
    assert accent("rpi2") == "[cyan]rpi2[/]"
    assert muted("prestart") == "[dim]prestart[/]"
