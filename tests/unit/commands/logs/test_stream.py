"""Tests for the log stream readers and the shared printer."""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING

import httpx  # respx-bundled; used to build sequenced mock responses
import pytest

from nd.commands.logs import stream as stream_mod
from nd.commands.logs.lines import (
    LOST_STREAM_MESSAGE,
    LineFilter,
    LogLine,
    LogSource,
    PrefixFormatter,
    lost_stream_line,
)
from nd.commands.logs.stream import RECONNECTED_MESSAGE, QueueItem, TaskStreamReader, print_queue
from tests.helpers import NOMAD_TEST_ADDR, capture_output, run_with_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import respx

    from nd.nomad import NomadClient

SOURCE = LogSource(group="web", task="app", alloc_id="3f2a1b9c-aaaa-bbbb-cccc-000000000000")
LOGS_URL = f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/{SOURCE.alloc_id}"


def _drain(queue: asyncio.Queue[QueueItem]) -> list[QueueItem]:
    items: list[QueueItem] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


@pytest.fixture(autouse=True)
def _no_reconnect_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream_mod, "LOGS_RECONNECT_DELAYS_SECONDS", (0.0,))


def _mock_tail_read(httpx2_mock: respx.Router, content: bytes = b"") -> respx.Route:
    """Answer the non-following reads, which show the log holds `content`."""
    return httpx2_mock.get(LOGS_URL, params__contains={"follow": "false"}).respond(content=content)


def _follow(*, backlog_lines: int | None, live_answers: list[bool]) -> list[QueueItem]:
    """Run a reader whose `is_live` returns each answer in turn, then False."""
    queue: asyncio.Queue[QueueItem] = asyncio.Queue()
    answers = iter(live_answers)

    async def call(client: NomadClient) -> None:
        await TaskStreamReader(
            client,
            source=SOURCE,
            stream="stderr",
            backlog_lines=backlog_lines,
            queue=queue,
            is_live=lambda: next(answers, False),
            show_group=True,
        ).run()

    run_with_client(call)
    return _drain(queue)


def _plain(items: list[QueueItem]) -> list[str]:
    return [item.text if isinstance(item, LogLine) else item.plain for item in items]


LOST = f"x web/app[3f2a1b9c] {LOST_STREAM_MESSAGE}: "
RECONNECTED = f"+ web/app[3f2a1b9c] {RECONNECTED_MESSAGE}"


def test_task_stream_reader_puts_lines(httpx2_mock: respx.Router) -> None:
    """Verify each streamed line reaches the queue with its source and stream."""
    # Given an empty log and a follow stream carrying two lines, with no backlog wanted
    _mock_tail_read(httpx2_mock)
    httpx2_mock.get(LOGS_URL, params__contains={"follow": "true"}).respond(content=b"a\nb\n")

    # When the reader follows a task whose allocation is terminal when the stream ends
    items = _follow(backlog_lines=0, live_answers=[])

    # Then the queue holds both lines from that task's stderr and nothing else
    assert items == [
        LogLine(source=SOURCE, stream="stderr", text="a"),
        LogLine(source=SOURCE, stream="stderr", text="b"),
    ]


@pytest.mark.parametrize(
    ("backlog_lines", "log", "expected_old", "expected_follow", "follow_body"),
    [
        pytest.param(
            20, b"old\n", ["old"], ("end", "1"), b"\nnew\n", id="last-lines-then-new-output"
        ),
        pytest.param(
            None, b"old\n", ["old"], ("start", "4"), b"new\n", id="whole-log-then-new-output"
        ),
        pytest.param(
            None, b"old\npart", ["old"], ("start", "4"), b"new\n", id="whole-log-resumes-a-cut-line"
        ),
    ],
)
def test_task_stream_reader_puts_backlog_before_new_output(
    httpx2_mock: respx.Router,
    backlog_lines: int | None,
    log: bytes,
    expected_old: list[str],
    expected_follow: tuple[str, str],
    follow_body: bytes,
) -> None:
    """Verify the backlog comes first and the follow never repeats it.

    A backlog of last lines is read, then the follow starts at the last byte of the log. The whole
    log is read before the follow, which resumes after its last complete line, so a task that
    already ended prints all of it before the grace period can stop the reader.
    """

    # Given a log whose read returns the old output and whose follow carries a new line
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params["follow"] == "false":
            return httpx.Response(200, content=log)
        return httpx.Response(200, content=follow_body)

    route = httpx2_mock.get(LOGS_URL).mock(side_effect=respond)

    # When the reader runs
    items = _follow(backlog_lines=backlog_lines, live_answers=[])

    # Then the old lines come first, once, and the follow starts where the backlog left off
    assert _plain(items) == [*expected_old, "new"]
    calls = [call.request.url.params for call in route.calls]
    assert sum(params["follow"] == "false" for params in calls) == 1
    assert (calls[-1]["origin"], calls[-1]["offset"]) == expected_follow


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        (
            [httpx.Response(500), httpx.Response(200, content=b"\nx\n")],
            ["LOST", RECONNECTED, "x"],
        ),
        ([httpx.Response(500), httpx.Response(200)], ["LOST", RECONNECTED]),
        (
            [httpx.Response(200, content=b"\na\n"), httpx.Response(200)],
            ["a", LOST + stream_mod.STREAM_CLOSED_REASON, RECONNECTED],
        ),
    ],
    ids=["after-error", "quiet-stream", "after-clean-end"],
)
def test_task_stream_reader_reconnects_while_live(
    httpx2_mock: respx.Router, responses: list[httpx.Response], expected: list[str]
) -> None:
    """Verify a lost or closed stream of a live allocation reconnects without the backlog."""
    # Given a one-line backlog and a follow stream that fails or ends once
    tail_route = httpx2_mock.get(LOGS_URL, params__contains={"follow": "false"}).respond(
        text="old\n"
    )
    follow_route = httpx2_mock.get(LOGS_URL, params__contains={"follow": "true"})
    follow_route.side_effect = responses

    # When the reader follows an allocation that stays live until the second stream ends
    items = _follow(backlog_lines=20, live_answers=[True, True])

    # Then the backlog prints once, the lost and reconnected lines show even with no new
    # output, and the reconnect starts from the end of the log
    plain = _plain(items)
    assert plain[0] == "old"
    assert len(plain) == len(expected) + 1
    for got, want in zip(plain[1:], expected, strict=True):
        if want == "LOST":
            assert got.startswith(LOST)
        else:
            assert got == want
    assert tail_route.call_count == 1
    assert follow_route.call_count == 2
    reconnect_params = follow_route.calls[1].request.url.params
    assert (reconnect_params["origin"], reconnect_params["offset"]) == ("end", "1")


@pytest.mark.parametrize(
    "live_answers",
    [[], [True]],
    ids=["terminal-at-error", "terminal-after-backoff"],
)
def test_task_stream_reader_stops_when_alloc_terminal(
    httpx2_mock: respx.Router, live_answers: list[bool]
) -> None:
    """Verify a lost stream of a terminal allocation reports once and does not reconnect."""
    # Given an empty log and a follow stream that fails
    _mock_tail_read(httpx2_mock)
    route = httpx2_mock.get(LOGS_URL, params__contains={"follow": "true"}).respond(500)

    # When the allocation is terminal at the error, or turns terminal during the backoff
    items = _follow(backlog_lines=0, live_answers=live_answers)

    # Then one lost-stream line arrives and the reader makes no second request
    plain = _plain(items)
    assert len(plain) == 1
    assert plain[0].startswith(LOST)
    assert route.call_count == 1


def test_print_queue_applies_filter() -> None:
    """Verify the printer drops excluded log lines but always prints lifecycle lines."""
    # Given a queue with a kept line, an excluded line, and a lifecycle line the exclude
    # pattern matches, and a recording console
    console = capture_output()
    line_filter = LineFilter(exclude=(re.compile("noise"),))
    formatter = PrefixFormatter(show_group=True, show_prefix=True)

    async def run() -> None:
        queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        queue.put_nowait(LogLine(source=SOURCE, stream="stdout", text="keep me"))
        queue.put_nowait(LogLine(source=SOURCE, stream="stdout", text="noise here"))
        queue.put_nowait(lost_stream_line(SOURCE, reason="noise", show_group=True))
        printer = asyncio.create_task(
            print_queue(queue, line_filter=line_filter, formatter=formatter)
        )
        await queue.join()
        printer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await printer

    # When the printer drains the queue
    asyncio.run(run())

    # Then the kept and lifecycle lines printed, and the excluded line did not
    output = console.export_text()
    assert "keep me" in output
    assert "noise here" not in output
    assert f"{LOST_STREAM_MESSAGE}: noise" in output


def test_task_stream_reader_prints_unfinished_line_when_stopped(httpx2_mock: respx.Router) -> None:
    """Verify a last line with no newline reaches the queue when the reader is stopped."""
    # Given an empty log and a follow stream that sends a line and half of another, then
    # stays open
    _mock_tail_read(httpx2_mock)

    async def body() -> AsyncIterator[bytes]:
        yield b"done\nhal"
        await asyncio.Event().wait()

    httpx2_mock.get(LOGS_URL, params__contains={"follow": "true"}).mock(
        return_value=httpx.Response(200, content=body())
    )
    queue: asyncio.Queue[QueueItem] = asyncio.Queue()
    items: list[QueueItem] = []

    async def call(client: NomadClient) -> None:
        reader = asyncio.create_task(
            TaskStreamReader(
                client,
                source=SOURCE,
                stream="stdout",
                backlog_lines=0,
                queue=queue,
                is_live=lambda: True,
                show_group=True,
            ).run()
        )
        items.append(await queue.get())
        # When the reader is stopped, as the view stops the reader of an ended task
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader

    run_with_client(call)

    # Then the unfinished line arrives after the complete one
    assert _plain([*items, *_drain(queue)]) == ["done", "hal"]


@pytest.mark.parametrize(
    ("backlog_lines", "failing"),
    [
        pytest.param(20, {"follow": "false"}, id="backlog-read-fails"),
        pytest.param(0, {"follow": "true"}, id="follow-fails"),
    ],
)
def test_task_stream_reader_sets_backlog_done_however_it_ends(
    httpx2_mock: respx.Router, backlog_lines: int, failing: dict[str, str]
) -> None:
    """Verify a reader that fails before any stream opens still marks its backlog done."""
    # Given a log read that fails and a task that is no longer live
    if failing["follow"] == "true":
        _mock_tail_read(httpx2_mock)
    httpx2_mock.get(LOGS_URL, params__contains=failing).respond(500)
    reader_holder: list[TaskStreamReader] = []

    async def call(client: NomadClient) -> None:
        reader = TaskStreamReader(
            client,
            source=SOURCE,
            stream="stdout",
            backlog_lines=backlog_lines,
            queue=asyncio.Queue(),
            is_live=lambda: False,
            show_group=True,
        )
        reader_holder.append(reader)
        await reader.run()

    # When the reader runs to its end
    run_with_client(call)

    # Then a caller waiting for the backlog is released
    assert reader_holder[0].backlog_done.is_set()


@pytest.mark.parametrize(
    ("first_chunks", "expected"),
    [
        pytest.param([b"\nnew line\n"], ["new line"], id="last-byte-is-a-newline"),
        pytest.param([b"rest of old\nnew line\n"], ["new line"], id="last-byte-is-mid-line"),
        pytest.param([b"rest", b" of old\nnew line\n"], ["new line"], id="rest-arrives-in-pieces"),
    ],
)
def test_task_stream_reader_follows_from_last_byte_without_repeating_it(
    httpx2_mock: respx.Router, first_chunks: list[bytes], expected: list[str]
) -> None:
    """Verify a follow after a backlog drops the printed line's tail and prints no blank line."""

    # Given a non-empty backlog and a follow that begins with the log's last byte
    async def body() -> AsyncIterator[bytes]:
        for chunk in first_chunks:
            yield chunk

    _mock_tail_read(httpx2_mock, b"old\n")
    follow_route = httpx2_mock.get(LOGS_URL, params__contains={"follow": "true"}).mock(
        return_value=httpx.Response(200, content=body())
    )

    # When the reader follows an allocation that is terminal when the stream ends
    items = _follow(backlog_lines=20, live_answers=[])

    # Then the follow asked for the last byte and only the new line printed after the backlog
    assert _plain(items) == ["old", *expected]
    params = follow_route.calls[0].request.url.params
    assert (params["origin"], params["offset"]) == ("end", "1")


def test_task_stream_reader_follows_empty_log_from_start(httpx2_mock: respx.Router) -> None:
    """Verify a follow after an empty backlog starts at the log's start and keeps the first line."""
    # Given an empty log whose follow carries a first line
    _mock_tail_read(httpx2_mock)
    follow_route = httpx2_mock.get(LOGS_URL, params__contains={"follow": "true"}).respond(
        content=b"first\n"
    )

    # When the reader follows with a backlog that finds nothing
    items = _follow(backlog_lines=20, live_answers=[])

    # Then the follow starts at the beginning and the first line prints
    assert _plain(items) == ["first"]
    params = follow_route.calls[0].request.url.params
    assert (params["origin"], params["offset"]) == ("start", "0")


@pytest.mark.parametrize(
    ("log", "expected_follow", "follow_body", "expected_lines"),
    [
        pytest.param(b"old\n", ("end", "1"), b"\nnew\n", ["new"], id="log-has-bytes"),
        pytest.param(b"", ("start", "0"), b"first\n", ["first"], id="log-is-empty"),
    ],
)
def test_task_stream_reader_probes_log_without_backlog(
    httpx2_mock: respx.Router,
    log: bytes,
    expected_follow: tuple[str, str],
    follow_body: bytes,
    expected_lines: list[str],
) -> None:
    """Verify a reader with no backlog reads one line first to pick where its follow starts."""
    # Given a log that is empty or holds a line
    tail_route = _mock_tail_read(httpx2_mock, log)
    follow_route = httpx2_mock.get(LOGS_URL, params__contains={"follow": "true"}).respond(
        content=follow_body
    )

    # When the reader follows with no backlog
    items = _follow(backlog_lines=0, live_answers=[])

    # Then it probed once, followed from the position that probe chose, and printed new lines only
    assert tail_route.call_count == 1
    params = follow_route.calls[0].request.url.params
    assert (params["origin"], params["offset"]) == expected_follow
    assert _plain(items) == expected_lines
