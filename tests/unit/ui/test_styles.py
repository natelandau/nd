"""Tests for shared UI status styles."""

from __future__ import annotations

import pytest
from rich.text import Text

from nd.ui.styles import status_cell


@pytest.mark.parametrize(
    ("status", "stopping", "expected"),
    [
        pytest.param("running", False, "✓ running", id="healthy"),
        pytest.param("mystery", False, "• mystery", id="unknown-is-neutral"),
        pytest.param("complete", True, "✓ stopped", id="stopping-terminal-reads-stopped"),
        pytest.param("running", True, "• running", id="stopping-running-is-pending"),
        pytest.param("pending", True, "• pending", id="stopping-pending-is-pending"),
        pytest.param("failed", True, "✗ failed", id="stopping-failed-stays-failure"),
        pytest.param("lost", True, "✗ lost", id="stopping-lost-stays-failure"),
    ],
)
def test_status_cell_glyph_and_label(status: str, *, stopping: bool, expected: str) -> None:
    """Verify a status cell's glyph and label, which invert to "stopped" during a stop."""
    # When rendering the status cell and stripping its markup
    cell = Text.from_markup(status_cell(status, stopping=stopping)).plain

    # Then the person sees the expected glyph and label
    assert cell == expected
