"""Color the parts of a log line that carry meaning: levels, times, addresses, keys."""

from __future__ import annotations

from rich.highlighter import RegexHighlighter

_IPV4 = r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?\b"
_HEX_GROUP = r"[0-9a-fA-F]{1,4}"
# Compressed form (has "::") or full form that must contain a hex letter, so clock times
# and other decimal colon runs never match.
_IPV6 = (
    rf"(?<![\w:])(?:(?:{_HEX_GROUP}:){{1,7}}:(?:{_HEX_GROUP}(?::{_HEX_GROUP}){{0,6}})?"
    rf"|::{_HEX_GROUP}(?::{_HEX_GROUP}){{0,6}}"
    rf"|(?=[0-9:]*[a-fA-F])(?:{_HEX_GROUP}:){{2,7}}{_HEX_GROUP})(?![\w:])"
)


class LogHighlighter(RegexHighlighter):
    """Style log levels, timestamps, IP addresses, UUIDs, URLs, numbers, keys, and strings.

    Patterns run in order and a later span wins an overlap, so the broad patterns come
    first and the specific ones (level, timestamp, IP, UUID, URL) override them. Styles
    come from ``styles.LOG_THEME``, which the console must have pushed.
    """

    base_style = "log."
    highlights = [  # noqa: RUF012
        r"(?P<string>\"[^\"\n]*\"|'[^'\n]*')",
        r"(?P<number>\b\d+(?:\.\d+)?\b)",
        r"(?P<key>\b[\w.-]+(?==))",
        rf"(?P<ip>{_IPV4}|{_IPV6})",
        r"(?P<uuid>\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b)",
        r"(?P<url>\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>]+)",
        r"(?P<timestamp>\b\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)",
        r"\b(?P<level_error>(?i:ERROR|ERR|FATAL|CRITICAL|PANIC))\b",
        r"\b(?P<level_warn>(?i:WARN|WARNING))\b",
        r"\b(?P<level_info>(?i:INFO))\b",
        r"\b(?P<level_debug>(?i:DEBUG|TRACE))\b",
    ]
