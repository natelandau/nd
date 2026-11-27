"""Tests for the pure line logic of the log view."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from nd.commands.logs.lines import (
    InvalidPatternError,
    LineFilter,
    LineSplitter,
    LogLine,
    LogSource,
    PrefixFormatter,
    StreamName,
    alloc_subject,
    lifecycle_line,
    task_subject,
)
from nd.ui import styles

if TYPE_CHECKING:
    from nd.ui.styles import LifecycleEvent

SOURCE = LogSource(group="web", task="app", alloc_id="3f2a1b9c-aaaa-bbbb-cccc-000000000000")
NO_FILTER = LineFilter()


def _line(text: str, *, stream: StreamName = "stdout", source: LogSource = SOURCE) -> LogLine:
    return LogLine(source=source, stream=stream, text=text)


def test_line_splitter_splits_across_chunks() -> None:
    """Verify lines complete across chunk boundaries and nothing is left to flush."""
    # Given a splitter fed chunks that cut a line in two
    splitter = LineSplitter()

    # When the chunks arrive
    first = splitter.feed(b"ab")
    second = splitter.feed(b"c\nde")
    third = splitter.feed(b"\n")

    # Then each line appears once complete
    assert (first, second, third) == ([], ["abc"], ["de"])
    assert splitter.flush() == []


def test_line_splitter_strips_carriage_returns() -> None:
    """Verify CRLF line endings leave no trailing carriage return."""
    # Given a splitter fed CRLF lines and an unfinished CRLF-less tail
    splitter = LineSplitter()

    # When fed
    lines = splitter.feed(b"a\r\nb\r\nc\r")

    # Then the lines carry no carriage return, including the flushed one
    assert lines == ["a", "b"]
    assert splitter.flush() == ["c"]


def test_line_splitter_flushes_partial_line() -> None:
    """Verify a final line with no newline is returned by flush."""
    # Given a splitter holding an unfinished line
    splitter = LineSplitter()
    splitter.feed(b"x")

    # When the stream ends
    # Then the partial line is returned
    assert splitter.flush() == ["x"]


def test_line_splitter_joins_split_multibyte_character() -> None:
    """Verify a character split between chunks decodes as one character."""
    # Given the two bytes of an e-acute split across chunks
    encoded = "é\n".encode()
    splitter = LineSplitter()

    # When fed one byte at a time
    lines = splitter.feed(encoded[:1]) + splitter.feed(encoded[1:])

    # Then one line holds the whole character
    assert lines == ["é"]


@pytest.mark.parametrize(
    ("include", "exclude", "text", "expected"),
    [
        ([], [], "anything", True),
        (["err"], [], "an err here", True),
        (["err"], [], "all fine", False),
        ([], ["noise"], "some noise", False),
        (["err"], ["noise"], "err noise", False),
    ],
    ids=["no-patterns", "include-hit", "include-miss", "exclude-hit", "exclude-beats-include"],
)
def test_line_filter_keeps(
    include: list[str], exclude: list[str], text: str, *, expected: bool
) -> None:
    """Verify include and exclude decide whether a line prints."""
    # Given a filter compiled from the patterns
    line_filter = LineFilter.compile(include=include, exclude=exclude, highlight=[])

    # When asked about a line
    # Then exclude wins and include requires a match
    assert line_filter.keeps(text) is expected


def test_line_filter_compile_rejects_invalid_regex() -> None:
    """Verify a bad pattern raises an error naming the pattern."""
    # Given a pattern that does not compile
    # When the filter compiles it
    with pytest.raises(InvalidPatternError) as caught:
        LineFilter.compile(include=["("], exclude=[], highlight=[])

    # Then the message shows the pattern
    assert "Invalid regex '('" in str(caught.value)


def test_line_filter_compile_builds_patterns_for_every_flag() -> None:
    """Verify compile produces regex objects for include, exclude, and highlight."""
    # Given patterns for each flag
    line_filter = LineFilter.compile(include=["a"], exclude=["b"], highlight=["c"])

    # Then each is a compiled pattern
    assert all(
        isinstance(p, re.Pattern)
        for p in (*line_filter.include, *line_filter.exclude, *line_filter.highlight)
    )


@pytest.mark.parametrize(
    ("show_group", "show_prefix", "expected_start"),
    [
        (False, True, "app[3f2a1b9c]"),
        (True, True, "web/app[3f2a1b9c]"),
        (True, False, "  hello"),
    ],
    ids=["one-group", "several-groups", "no-prefix"],
)
def test_format_line_prefix(*, show_group: bool, show_prefix: bool, expected_start: str) -> None:
    """Verify the prefix names group, task, and short allocation ID, or is omitted."""
    # Given a formatter
    formatter = PrefixFormatter(show_group=show_group, show_prefix=show_prefix)

    # When formatting a stdout line
    row = formatter.format(_line("hello"), NO_FILTER)

    # Then the row starts as expected and ends with the message
    assert row.plain.startswith(expected_start)
    assert row.plain.endswith("hello")


@pytest.mark.parametrize("short_first", [False, True], ids=["long-first", "short-first"])
def test_format_line_aligns_messages_after_prefix_widens(*, short_first: bool) -> None:
    """Verify a shorter prefix pads to the widest seen so the messages align."""
    # Given two tasks of different name lengths, the short one perhaps seen first
    formatter = PrefixFormatter(show_group=False, show_prefix=True)
    long_source = LogSource(group="web", task="proxy-server", alloc_id=SOURCE.alloc_id)
    if short_first:
        formatter.format(_line("@@"), NO_FILTER)

    # When both print
    long_row = formatter.format(_line("@@", source=long_source), NO_FILTER)
    short_row = formatter.format(_line("@@"), NO_FILTER)

    # Then the messages start in the same column
    assert short_row.plain.index("@@") == long_row.plain.index("@@")


def test_format_line_reserve_aligns_from_the_first_line() -> None:
    """Verify reserved sources set the prefix width before any of them prints."""
    # Given a formatter told about a short and a long task before printing
    formatter = PrefixFormatter(show_group=False, show_prefix=True)
    long_source = LogSource(group="web", task="proxy-server", alloc_id=SOURCE.alloc_id)
    formatter.reserve([SOURCE, long_source])

    # When the short task prints first
    short_row = formatter.format(_line("@@"), NO_FILTER)
    long_row = formatter.format(_line("@@", source=long_source), NO_FILTER)

    # Then its message already starts in the long task's column
    assert short_row.plain.index("@@") == long_row.plain.index("@@")


def test_format_line_marks_stderr() -> None:
    """Verify only stderr lines carry the marker glyph."""
    # Given a formatter
    formatter = PrefixFormatter(show_group=False, show_prefix=True)

    # When formatting each stream
    err = formatter.format(_line("boom", stream="stderr"), NO_FILTER)
    out = formatter.format(_line("fine"), NO_FILTER)

    # Then the glyph appears on stderr alone
    assert styles.LOG_STDERR_GLYPH in err.plain
    assert styles.LOG_STDERR_GLYPH not in out.plain


def test_format_line_keeps_brackets_and_strips_escapes() -> None:
    """Verify workload text is never parsed as markup and loses terminal controls."""
    # Given a line with markup-like text and an escape sequence
    formatter = PrefixFormatter(show_group=False, show_prefix=False)

    # When formatting it
    row = formatter.format(_line("[red]x\x1b[2J"), NO_FILTER)

    # Then the brackets stay literal and the escape is gone
    assert row.plain.endswith("[red]x")
    assert "\x1b" not in row.plain


def test_format_line_highlight_spans() -> None:
    """Verify each --highlight match gets the match style."""
    # Given a filter that highlights "err"
    line_filter = LineFilter.compile(include=[], exclude=[], highlight=["err"])
    formatter = PrefixFormatter(show_group=False, show_prefix=False)

    # When formatting a line containing it
    row = formatter.format(_line("an err here"), line_filter)

    # Then a span with the match style covers exactly the match
    start = row.plain.index("err")
    assert any(
        span.style == styles.LOG_MATCH_STYLE and (span.start, span.end) == (start, start + 3)
        for span in row.spans
    )


def test_format_line_cycles_palette() -> None:
    """Verify task colors repeat once the palette runs out."""
    # Given more tasks than palette colors
    formatter = PrefixFormatter(show_group=False, show_prefix=True)
    count = len(styles.LOG_TASK_PALETTE) + 1
    rows = [
        formatter.format(
            _line("m", source=LogSource(group="g", task=f"t{i}", alloc_id=SOURCE.alloc_id)),
            NO_FILTER,
        )
        for i in range(count)
    ]

    # When comparing the first and the wrapped task
    # Then both use the first palette color
    assert rows[0].spans[0].style == rows[-1].spans[0].style == styles.LOG_TASK_PALETTE[0]


@pytest.mark.parametrize(
    ("event", "subject", "expected"),
    [
        pytest.param(
            "started", task_subject(SOURCE, show_group=True), "+ web/app[3f2a1b9c] msg", id="task"
        ),
        pytest.param(
            "stopped",
            task_subject(SOURCE, show_group=False),
            "- app[3f2a1b9c] msg",
            id="task-without-group",
        ),
        pytest.param(
            "failed",
            alloc_subject(group="web", alloc_id=SOURCE.alloc_id),
            "x web[3f2a1b9c] msg",
            id="allocation",
        ),
        pytest.param("waiting", "web\x1b[2J", ". web msg", id="job-strips-escapes"),
    ],
)
def test_lifecycle_line_text(*, event: LifecycleEvent, subject: str, expected: str) -> None:
    """Verify a lifecycle line shows its event's glyph, then its subject and message."""
    # When formatting the event
    text = lifecycle_line(event, subject=subject, message="msg")

    # Then the line reads as the spec shows, with no terminal control left
    assert text.plain == expected


def test_format_line_applies_highlighter_to_message() -> None:
    """Verify the message gets the log highlighter styles."""
    # Given a formatter
    formatter = PrefixFormatter(show_group=False, show_prefix=False)

    # When formatting a line with a log level
    row = formatter.format(_line("ERROR boom"), NO_FILTER)

    # Then the level has its style
    assert any(span.style == "log.level_error" for span in row.spans)
