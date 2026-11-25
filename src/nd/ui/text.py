"""Shared text formatting helpers for command output."""

from __future__ import annotations


def plural(count: int, noun: str) -> str:
    """Pair a count with its noun so output reads ``1 job`` and ``2 jobs``.

    Only appends ``s``, which covers every noun nd counts.

    Args:
        count: How many there are.
        noun: The singular noun.

    Returns:
        str: The count followed by the singular or plural noun.
    """
    return f"{count} {noun}{'' if count == 1 else 's'}"
