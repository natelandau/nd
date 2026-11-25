"""Tests for shared text formatting helpers."""

from __future__ import annotations

import pytest

from nd.ui.text import plural, strip_terminal_controls


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "0 jobs"), (1, "1 job"), (2, "2 jobs")],
)
def test_plural_uses_singular_only_for_one(count: int, expected: str) -> None:
    """Verify the noun is singular for exactly one and plural otherwise."""
    assert plural(count=count, noun="job") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("plain\ttext", "plain\ttext", id="keeps-tab"),
        pytest.param("\x1b[31mred\x1b[0m", "red", id="color"),
        pytest.param("a\x1b[2Jb", "ab", id="clear-screen"),
        pytest.param("x\x1b]52;c;SGVsbG8=\x07y", "xy", id="clipboard-write-bel"),
        pytest.param("x\x1b]52;c;SGVsbG8=\x1b\\y", "xy", id="clipboard-write-st"),
        pytest.param("q\x1bcz", "qz", id="terminal-reset"),
        pytest.param("a\x1b[2\x08Jb", "a2Jb", id="sequence-split-by-backspace"),
        pytest.param("a\x9b2Jb", "a2Jb", id="c1-control"),
        pytest.param("a\rb\x07", "ab", id="carriage-return-and-bell"),
    ],
)
def test_strip_terminal_controls_leaves_only_printable_text(text: str, expected: str) -> None:
    """Verify escape sequences and control characters cannot reach the terminal."""
    # Given untrusted text carrying terminal control
    # When stripping it
    # Then only printable characters, tabs, and newlines remain
    assert strip_terminal_controls(text) == expected
