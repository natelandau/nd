"""Shared helpers for Nomad models."""

from __future__ import annotations

import datetime as dt

_NANOS_PER_SECOND = 1_000_000_000


def ns_to_datetime(nanos: int) -> dt.datetime:
    """Convert a Nomad nanosecond-epoch timestamp to an aware UTC datetime."""
    return dt.datetime.fromtimestamp(nanos / _NANOS_PER_SECOND, tz=dt.UTC)
