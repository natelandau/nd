"""Tests for shared duration formatting."""

from __future__ import annotations

from nd.ui.duration import fmt_elapsed, fmt_uptime


def test_fmt_elapsed_pads_minutes_and_seconds() -> None:
    """Verify elapsed time renders as H:MM:SS with zero-padding."""
    assert fmt_elapsed(0) == "0:00:00"
    assert fmt_elapsed(65) == "0:01:05"
    assert fmt_elapsed(3661) == "1:01:01"


def test_fmt_uptime_buckets() -> None:
    """Verify uptime collapses to the two most significant units."""
    # Given a fixed now and submit times expressed in nanoseconds
    now = 1_000_000.0
    one_hour_ago_ns = int((now - 3600) * 1_000_000_000)
    five_min_ago_ns = int((now - 300) * 1_000_000_000)
    # Then
    assert fmt_uptime(one_hour_ago_ns, now) == "1h 0m"
    assert fmt_uptime(five_min_ago_ns, now) == "5m"


def test_fmt_uptime_non_positive() -> None:
    """Verify missing or future submit times render as a dash."""
    assert fmt_uptime(0, 1_000_000.0) == "-"
    assert fmt_uptime((2_000_000 * 1_000_000_000), 1_000_000.0) == "-"
