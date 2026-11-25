"""Shared text formatting helpers for command output."""

from __future__ import annotations

import re

from rich.markup import escape

_SHORT_ID_LENGTH = 8
# Complete escape sequences: CSI (colors, cursor moves), OSC (titles, clipboard, links)
# ended by BEL or ST, and the two-byte forms such as ESC c (terminal reset).
_ESCAPE_SEQUENCE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[ -~]"
)
# Every C0 control but tab and newline, plus DEL and the C1 controls. ESC is included,
# so a sequence split by a control character cannot rejoin once that character is gone.
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def strip_terminal_controls(text: str) -> str:
    """Remove escape sequences and control characters so text prints as plain characters.

    Use it on any text the cluster or a workload supplies, such as log lines and task
    events, before printing it: a raw escape sequence there could write the clipboard,
    clear the screen, or reset the terminal.

    Args:
        text: Untrusted text.

    Returns:
        str: The text with only printable characters, tabs, and newlines.
    """
    return _CONTROL_CHARACTER.sub("", _ESCAPE_SEQUENCE.sub("", text))


def untrusted_markup(text: str) -> str:
    """Make untrusted text safe to embed in Rich markup.

    Args:
        text: Untrusted text, such as a task name or event message from the cluster.

    Returns:
        str: The text with control characters removed and markup brackets escaped.
    """
    return escape(strip_terminal_controls(text))


def short_id(identifier: str) -> str:
    """Shorten a Nomad UUID to its first characters, as the Nomad CLI and UI show it.

    Args:
        identifier: A full allocation, node, or other Nomad ID.

    Returns:
        str: The ID's first eight characters.
    """
    return identifier[:_SHORT_ID_LENGTH]


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
