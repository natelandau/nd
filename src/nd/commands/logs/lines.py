"""Pure line logic for the log view: splitting, filtering, prefixing, and coloring."""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from rich.text import Text

from nd.ui import styles
from nd.ui.log_highlight import LogHighlighter
from nd.ui.text import short_id, strip_terminal_controls

if TYPE_CHECKING:
    from collections.abc import Iterable

    from nd.ui.styles import LifecycleEvent

type StreamName = Literal["stdout", "stderr"]
LOST_STREAM_MESSAGE = "log stream lost"
_highlighter = LogHighlighter()
_STDERR_MARKER = Text(styles.LOG_STDERR_GLYPH, style=styles.LOG_STDERR_STYLE)
# Stdout lines keep the marker column blank so messages align across streams
_STDOUT_MARKER = Text(" " * len(styles.LOG_STDERR_GLYPH))


@dataclass(frozen=True)
class LogSource:
    """The task of one allocation that a log line came from.

    Attributes:
        group: The task group name.
        task: The task name.
        alloc_id: The full allocation ID.
    """

    group: str
    task: str
    alloc_id: str

    def label(self, *, show_group: bool) -> str:
        """Name the task for a prefix or lifecycle line, as ``group/task`` or ``task``.

        Args:
            show_group: Whether to include the task group, as a job with several groups needs.

        Returns:
            str: The label.
        """
        return f"{self.group}/{self.task}" if show_group else self.task


@dataclass(frozen=True)
class LogLine:
    """One complete line of task output.

    Attributes:
        source: Where the line came from.
        stream: Which log stream carried it.
        text: The line without its newline.
    """

    source: LogSource
    stream: StreamName
    text: str


class LineSplitter:
    """Turn arbitrary byte chunks of a log stream into complete lines.

    Use one per stream. A chunk can end mid-line or mid-character, so the splitter
    holds the partial remainder until the rest arrives.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending = ""

    def feed(self, chunk: bytes) -> list[str]:
        """Add a chunk and return the lines it completed.

        Args:
            chunk: The next bytes of the stream.

        Returns:
            list[str]: Newly completed lines, without newlines.
        """
        self._pending += self._decoder.decode(chunk)
        *complete, self._pending = self._pending.split("\n")
        return [line.removesuffix("\r") for line in complete]

    def flush(self) -> list[str]:
        """Return the unfinished last line when the stream ends.

        Returns:
            list[str]: The remaining partial line, or an empty list.
        """
        self._pending += self._decoder.decode(b"", final=True)
        remainder, self._pending = self._pending, ""
        return [remainder.removesuffix("\r")] if remainder else []


class InvalidPatternError(ValueError):
    """Raised when a line filter pattern is not a valid regular expression."""


def _compile_pattern(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:
        msg = f"Invalid regex {pattern!r}: {exc}"
        raise InvalidPatternError(msg) from exc


@dataclass(frozen=True)
class LineFilter:
    """Include, exclude, and highlight patterns, matched against the message only.

    Attributes:
        include: A line prints only if it matches one of these, when any are given.
        exclude: A line matching any of these never prints, even when included.
        highlight: Matches in a printed line get ``styles.LOG_MATCH_STYLE``.
    """

    include: tuple[re.Pattern[str], ...] = ()
    exclude: tuple[re.Pattern[str], ...] = ()
    highlight: tuple[re.Pattern[str], ...] = ()

    @classmethod
    def compile(cls, *, include: list[str], exclude: list[str], highlight: list[str]) -> LineFilter:
        """Compile the regex flags of a command.

        Args:
            include: Include pattern sources.
            exclude: Exclude pattern sources.
            highlight: Highlight pattern sources.

        Returns:
            LineFilter: The compiled filter.

        Raises:
            InvalidPatternError: If a pattern is not a valid regular expression.
        """
        return cls(
            include=tuple(_compile_pattern(p) for p in include),
            exclude=tuple(_compile_pattern(p) for p in exclude),
            highlight=tuple(_compile_pattern(p) for p in highlight),
        )

    def keeps(self, text: str) -> bool:
        """Say whether a line should print.

        Args:
            text: The message of the line.

        Returns:
            bool: False when an exclude matches or includes exist and none match.
        """
        if any(p.search(text) for p in self.exclude):
            return False
        return not self.include or any(p.search(text) for p in self.include)


class PrefixFormatter:
    """Format log lines as aligned, colored ``group/task[alloc]`` rows.

    Colors go to each task name and allocation ID in order of first appearance, so the
    same task keeps its color for the whole run. The prefix pads to the widest seen so
    far, so messages align after the first few lines.
    """

    def __init__(self, *, show_group: bool, show_prefix: bool) -> None:
        self._show_group = show_group
        self._show_prefix = show_prefix
        self._task_styles: dict[str, str] = {}
        self._alloc_styles: dict[str, str] = {}
        self._width = 0
        # Prefixes are built once per source, and padded again only when the width grows
        self._prefixes: dict[LogSource, Text] = {}
        self._padded: dict[LogSource, Text] = {}

    @staticmethod
    def _style_for(known: dict[str, str], key: str, palette: tuple[str, ...]) -> str:
        if key not in known:
            known[key] = palette[len(known) % len(palette)]
        return known[key]

    def _build_prefix(self, source: LogSource) -> Text:
        task_style = self._style_for(self._task_styles, source.task, styles.LOG_TASK_PALETTE)
        alloc_style = self._style_for(self._alloc_styles, source.alloc_id, styles.LOG_ALLOC_PALETTE)
        return Text.assemble(
            (strip_terminal_controls(source.label(show_group=self._show_group)), task_style),
            ("[", "dim"),
            (short_id(source.alloc_id), alloc_style),
            ("]", "dim"),
        )

    def _prefix(self, source: LogSource) -> Text:
        padded = self._padded.get(source)
        if padded is not None:
            return padded
        prefix = self._prefixes.get(source)
        if prefix is None:
            prefix = self._prefixes[source] = self._build_prefix(source)
        if prefix.cell_len > self._width:
            self._width = prefix.cell_len
            self._padded.clear()
        padded = prefix.copy()
        padded.pad_right(self._width - prefix.cell_len)
        self._padded[source] = padded
        return padded

    def reserve(self, sources: Iterable[LogSource]) -> None:
        """Widen the prefix to fit every given source before any of them prints.

        Use it for a static view that knows all its sources up front, so the message column
        does not move between blocks. Colors go to the sources in the order given.

        Args:
            sources: The sources whose lines will print.
        """
        for source in sources:
            self._prefix(source)

    def format(self, line: LogLine, line_filter: LineFilter) -> Text:
        """Build the printable row for one line.

        Args:
            line: The line to format.
            line_filter: Supplies the highlight patterns.

        Returns:
            Text: The row, built as plain text so workload output never parses as markup.
        """
        message = _highlighter(Text(strip_terminal_controls(line.text)))
        for pattern in line_filter.highlight:
            for match in pattern.finditer(message.plain):
                if match.end() > match.start():
                    message.stylize(styles.LOG_MATCH_STYLE, match.start(), match.end())
        marker = _STDERR_MARKER if line.stream == "stderr" else _STDOUT_MARKER
        row = Text()
        if self._show_prefix:
            row.append_text(self._prefix(line.source))
            row.append(" ")
        row.append_text(marker)
        row.append(" ")
        row.append_text(message)
        return row


def lifecycle_line(event: LifecycleEvent, *, subject: str, message: str) -> Text:
    """Format a dim line that reports what happened to a task, allocation, or job.

    Lifecycle lines are never filtered, so they always show where output starts and stops.

    Args:
        event: What happened, which picks the glyph.
        subject: What the event concerns, such as from `task_subject` or `alloc_subject`.
        message: What to say about it.

    Returns:
        Text: The dim line, with the event's glyph first.
    """
    return Text(
        f"{styles.LOG_LIFECYCLE_GLYPH[event]} {strip_terminal_controls(subject)} "
        f"{strip_terminal_controls(message)}",
        style=styles.LOG_LIFECYCLE_STYLE,
    )


def task_subject(source: LogSource, *, show_group: bool) -> str:
    """Name a task of one allocation for a lifecycle line, such as ``web/app[3f2a1b9c]``.

    Args:
        source: The task.
        show_group: Whether to include the task group.

    Returns:
        str: The subject.
    """
    return f"{source.label(show_group=show_group)}[{short_id(source.alloc_id)}]"


def alloc_subject(*, group: str, alloc_id: str) -> str:
    """Name a whole allocation for a lifecycle line, such as ``web[3f2a1b9c]``.

    Args:
        group: The allocation's task group.
        alloc_id: The full allocation ID.

    Returns:
        str: The subject.
    """
    return f"{group}[{short_id(alloc_id)}]"


def lost_stream_line(source: LogSource, *, reason: str, show_group: bool) -> Text:
    """Format the lifecycle line of a task log that could not be read or stopped streaming.

    Args:
        source: The task whose log was lost.
        reason: Why, such as the Nomad error.
        show_group: Whether to include the task group.

    Returns:
        Text: The dim line.
    """
    return lifecycle_line(
        "lost-stream",
        subject=task_subject(source, show_group=show_group),
        message=f"{LOST_STREAM_MESSAGE}: {reason}",
    )
