"""Tests for shared duration formatting."""

from __future__ import annotations

import pytest

from nd.ui.duration import fmt_elapsed, fmt_uptime

_NOW_S = 1_000_000.0


def _seconds_ago_ns(seconds: float) -> int:
    """Convert an age relative to `_NOW_S` into an epoch timestamp in nanoseconds.

    Returns:
        int: The timestamp.
    """
    return int((_NOW_S - seconds) * 1_000_000_000)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0:00:00"), (65, "0:01:05"), (3661, "1:01:01")],
)
def test_fmt_elapsed_pads_minutes_and_seconds(seconds: int, expected: str) -> None:
    """Verify elapsed time renders as H:MM:SS with zero-padding."""
    assert fmt_elapsed(seconds) == expected


@pytest.mark.parametrize(
    ("age_s", "expected"),
    [
        (90_000, "1d 1h"),
        (3700, "1h 1m"),
        (3600, "1h 0m"),
        (300, "5m"),
        (45, "45s"),
    ],
)
def test_fmt_uptime_buckets(age_s: int, expected: str) -> None:
    """Verify uptime collapses to the two most significant units."""
    assert fmt_uptime(submit_time_ns=_seconds_ago_ns(age_s), now_s=_NOW_S) == expected


@pytest.mark.parametrize(
    "submit_ns",
    [pytest.param(0, id="missing"), pytest.param(_seconds_ago_ns(-1_000_000), id="future")],
)
def test_fmt_uptime_non_positive(submit_ns: int) -> None:
    """Verify missing or future submit times render as a dash."""
    assert fmt_uptime(submit_time_ns=submit_ns, now_s=_NOW_S) == "-"
