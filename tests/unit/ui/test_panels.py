"""Tests for shared UI panel builders."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table

from nd.ui.panels import status_table, titled_panel


def test_titled_panel_defaults() -> None:
    """Verify the panel is left-titled, cyan, and non-expanding by default."""
    # When
    panel = titled_panel("body", "My Title")
    # Then
    assert isinstance(panel, Panel)
    assert panel.title == "My Title"
    assert panel.title_align == "left"
    assert panel.border_style == "cyan"
    assert panel.expand is False


def test_titled_panel_custom_border() -> None:
    """Verify the border style is overridable."""
    panel = titled_panel("body", "T", border_style="yellow")
    assert panel.border_style == "yellow"


def test_status_table_adds_columns() -> None:
    """Verify the table is created with one column per header."""
    # When
    table = status_table("NAME", "STATUS")
    # Then
    assert isinstance(table, Table)
    assert len(table.columns) == 2
    assert [c.header for c in table.columns] == ["NAME", "STATUS"]
