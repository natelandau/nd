"""Shared stand-ins for live-panel callbacks in command tests."""

from collections.abc import Sequence

from nd.ui.live_panel import LiveChild


def discard_panel_update(phase: str, children: Sequence[LiveChild] = ()) -> None:
    """Accept and drop a row update, for tests that do not inspect the live panel."""
