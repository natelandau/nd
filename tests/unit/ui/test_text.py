"""Tests for shared text formatting helpers."""

from __future__ import annotations

import pytest

from nd.ui.text import plural


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "0 jobs"), (1, "1 job"), (2, "2 jobs")],
)
def test_plural_uses_singular_only_for_one(count: int, expected: str) -> None:
    """Verify the noun is singular for exactly one and plural otherwise."""
    assert plural(count=count, noun="job") == expected
