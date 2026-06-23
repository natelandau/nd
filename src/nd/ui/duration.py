"""Shared duration formatting helpers."""

from __future__ import annotations


def fmt_elapsed(seconds: float) -> str:
    """Format an elapsed duration as ``H:MM:SS`` for live panels."""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def summary_title(verb: str, done: int, total: int, seconds: float) -> str:
    """Build a final live-panel title like ``Deployed 2 jobs · 5s``.

    Shows ``N of M jobs`` when only some of the work succeeded so a partial result
    reads clearly. Shared by the commands that end on a live panel.
    """
    noun = f"{done} job{'s' if done != 1 else ''}" if done == total else f"{done} of {total} jobs"
    return f"{verb} {noun} · {int(seconds)}s"


def fmt_uptime(submit_time_ns: int, now_s: float) -> str:
    """Format a job's time-since-submit as a compact human duration.

    Collapses to the two most significant units (``2d 3h``, ``5m``, ``12s``) and
    renders ``-`` when the submit time is missing or in the future.
    """
    if submit_time_ns <= 0:
        return "-"
    seconds = int(now_s - submit_time_ns / 1_000_000_000)
    if seconds < 0:
        return "-"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"
