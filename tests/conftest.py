"""Shared test fixtures."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture
def plain() -> Callable[[str], str]:
    """Return a callable that strips ANSI styling from rendered CLI output.

    Use it to assert on any message Typer or Rich renders. Typer forces a colored
    terminal whenever ``GITHUB_ACTIONS``, ``FORCE_COLOR``, or ``PY_COLORS`` is set, and
    Rich's highlighter then splits option-like words into separate styled spans
    (``--shell`` becomes ``-`` plus ``-shell``), so a raw substring match passes locally
    and fails in CI.
    """
    return lambda text: _ANSI_ESCAPE.sub("", text)
