"""Shared Rich panel and table builders for nd commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich import box
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from rich.console import RenderableType


def titled_panel(
    body: RenderableType, title: str, *, border_style: str = "cyan", expand: bool = False
) -> Panel:
    """Wrap a renderable in nd's standard left-titled panel.

    ``expand`` defaults to False (shrink to content); pass True for full-width
    dashboard panels that should fill the terminal.
    """
    return Panel(body, title=title, title_align="left", border_style=border_style, expand=expand)


def status_table(*columns: str) -> Table:
    """Build a borderless status table with the given column headers."""
    table = Table(box=box.SIMPLE, expand=True, pad_edge=False)
    for column in columns:
        table.add_column(column)
    return table
