"""Tests for the log line highlighter."""

from __future__ import annotations

import pytest
from rich.text import Text

from nd.ui.log_highlight import LogHighlighter

UUID = "123e4567-e89b-12d3-a456-426614174000"


@pytest.mark.parametrize(
    ("message", "token", "style"),
    [
        ("ERROR", "ERROR", "log.level_error"),
        ("a WARN b", "WARN", "log.level_warn"),
        ("x info y", "info", "log.level_info"),
        ("DEBUG", "DEBUG", "log.level_debug"),
        ("from 10.0.0.1 ok", "10.0.0.1", "log.ip"),
        (f"id {UUID}", UUID, "log.uuid"),
        ("see https://example.com/a?b=1", "https://example.com/a?b=1", "log.url"),
        ("at 2026-11-27T10:00:00Z", "2026-11-27T10:00:00Z", "log.timestamp"),
        ("fe80::1 up", "fe80::1", "log.ip"),
        ("2001:db8:85a3:0:0:8a2e:370:7334", "2001:db8:85a3:0:0:8a2e:370:7334", "log.ip"),
        ("2026/10/09 15:44:14 GET /", "15:44:14", "log.timestamp"),
        ("took 42 ms", "42", "log.number"),
        ("user=bob", "user", "log.key"),
        ('said "hi there"', '"hi there"', "log.string"),
    ],
)
def test_log_highlighter_styles(message: str, token: str, style: str) -> None:
    """Verify each kind of token gets its style, the most specific one winning an overlap."""
    # When highlighting the message
    text = LogHighlighter()(Text(message))

    # Then the last span covering the token's start carries the expected style
    start = message.index(token)
    covering = [s for s in text.spans if s.start <= start < s.end]
    assert covering[-1].style == style


@pytest.mark.parametrize("message", ["at 15:44:14 now", "t 10:00:00", "mac 00:11:22:33:44:55"])
def test_log_highlighter_ignores_decimal_colon_runs_as_ip(message: str) -> None:
    """Verify clock times and decimal-only colon runs are not colored as IP addresses."""
    # When highlighting
    text = LogHighlighter()(Text(message))

    # Then no span is an IP
    assert all(span.style != "log.ip" for span in text.spans)
