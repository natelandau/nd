"""Tests for shared UI panel builders."""

from __future__ import annotations

from nd.ui.panels import status_table


def test_status_table_adds_columns() -> None:
    """Verify the table is created with one column per header."""
    # When building a table with two headers
    table = status_table("NAME", "STATUS")

    # Then it has those columns in order
    assert [c.header for c in table.columns] == ["NAME", "STATUS"]
