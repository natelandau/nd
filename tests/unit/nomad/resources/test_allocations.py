"""Tests for the allocations resource."""

import json

import httpx  # respx-bundled; used to build mocked responses
import pytest
import respx

from tests.builders import alloc_stub, to_payload
from tests.helpers import NOMAD_TEST_ADDR, run_with_client


def test_list_decodes_allocations(httpx2_mock: respx.Router):
    """Verify allocations.list decodes the listing into stubs."""
    # Given a mocked allocations listing endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/allocations").respond(
        json=[to_payload(alloc_stub(node_id="n1"))]
    )

    # When listing allocations
    allocs = run_with_client(lambda client: client.allocations.list())

    # Then the irregular-cased node id decodes and the expected path was called
    assert allocs[0].node_id == "n1"
    assert route.calls.last.request.url.path == "/v1/allocations"


def test_signal_posts_signal_and_task(httpx2_mock: respx.Router):
    """Verify allocations.signal posts the signal and task name to the client endpoint."""
    # Given a mocked signal endpoint returning Nomad's empty object
    route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/client/allocation/a1/signal").respond(json={})

    # When signaling a named task
    run_with_client(lambda client: client.allocations.signal("a1", signal="SIGUSR1", task="server"))

    # Then the request carries both fields in Nomad's PascalCase form
    assert route.calls.last.request.url.path == "/v1/client/allocation/a1/signal"
    assert json.loads(route.calls.last.request.content) == {"Signal": "SIGUSR1", "Task": "server"}


@pytest.mark.parametrize(
    ("task", "all_tasks", "body"),
    [
        pytest.param("server", False, {"TaskName": "server"}, id="one-task"),
        pytest.param(None, False, {}, id="running-tasks"),
        pytest.param(None, True, {"AllTasks": True}, id="all-tasks"),
    ],
)
def test_restart_posts_the_requested_scope(httpx2_mock: respx.Router, task, all_tasks, body):
    """Verify allocations.restart sends only the fields for the requested restart scope."""
    # Given a mocked restart endpoint returning Nomad's empty object
    route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/client/allocation/a1/restart").respond(json={})

    # When restarting with the given scope
    run_with_client(lambda client: client.allocations.restart("a1", task=task, all_tasks=all_tasks))

    # Then the body carries exactly that scope, leaving Nomad's default when none is set
    assert json.loads(route.calls.last.request.content) == body


def test_tail_log_reads_plain_text_from_the_end(httpx2_mock: respx.Router):
    """Verify allocations.tail_log asks for the stream's end as plain text, without following."""
    # Given a mocked logs endpoint returning plain text
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/a1").respond(text="boom\n")

    # When reading the last lines of a task's stderr
    lines = run_with_client(
        lambda client: client.allocations.tail_log("a1", task="server", stream="stderr", lines=5)
    )

    # Then the request reads the stream from the end without following, as plain text
    params = dict(route.calls.last.request.url.params)
    assert params.pop("offset")
    assert params == {
        "task": "server",
        "type": "stderr",
        "origin": "end",
        "plain": "true",
        "follow": "false",
    }
    assert lines == ["boom"]


# With 200-byte lines, the first 8192-byte read for 41 lines holds 40 whole lines and a cut one
_LOG_LINE = "x" * 199


@pytest.mark.parametrize(
    ("log", "lines", "keepends", "expected"),
    [
        pytest.param("a\nb\nc\n", 2, False, ["b", "c"], id="line-limit"),
        pytest.param("a\r\nb\nc", 2, True, ["b\n", "c"], id="keeps-endings"),
        pytest.param("a\r\nb\n", 2, False, ["a", "b"], id="strips-crlf"),
        pytest.param(
            "a\n10%\r50%\r100%\nb\fc\n", 2, False, ["10%\r50%\r100%", "b\fc"], id="newline-only"
        ),
        pytest.param(f"{_LOG_LINE}\n" * 50, 41, False, [_LOG_LINE] * 41, id="drops-cut-first-line"),
        pytest.param("y" * 9000, 1, False, ["y" * 8192], id="keeps-a-cut-single-line"),
    ],
)
def test_tail_log_keeps_whole_last_lines(
    httpx2_mock: respx.Router, *, log: str, lines: int, keepends: bool, expected: list[str]
):
    """Verify a tail keeps the last lines and drops a first line that the byte limit cut."""
    # Given a log that answers each read with its last `offset` bytes
    content = log.encode()

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content[-int(request.url.params["offset"]) :])

    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/a1").mock(side_effect=respond)

    # When reading the last lines
    result = run_with_client(
        lambda client: client.allocations.tail_log(
            "a1", task="app", stream="stdout", lines=lines, keepends=keepends
        )
    )

    # Then only whole lines from the end remain
    assert result == expected


def test_tail_log_doubles_read_until_enough_lines(httpx2_mock: respx.Router):
    """Verify a byte estimate that undershoots the line length is doubled until it fits."""
    # Given 300-byte lines, which the 120-bytes-per-line estimate undersizes
    full = "".join(f"{n:03d}{'x' * 296}\n" for n in range(1, 201)).encode()

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=full[-int(request.url.params["offset"]) :])

    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/a1").mock(side_effect=respond)

    # When reading the last 100 lines (a 12000-byte first read holds about 40)
    lines = run_with_client(
        lambda client: client.allocations.tail_log("a1", task="app", stream="stdout", lines=100)
    )

    # Then the read doubled until 100 whole lines fit, and they are the last 100
    assert len(lines) == 100
    assert lines[0].startswith("101")
    budgets = [int(call.request.url.params["offset"]) for call in route.calls]
    assert budgets == [12000, 24000, 48000]


def test_follow_logs_sends_follow_params(httpx2_mock: respx.Router):
    """Verify follow_logs streams from the given origin and offset as plain text."""
    # Given a mocked logs endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/a1").respond(text="line\n")

    # When following a task's stderr
    async def collect(client) -> bytes:
        async with client.allocations.follow_logs(
            "a1", task="app", stream="stderr", origin="start", offset=8192
        ) as chunks:
            return b"".join([chunk async for chunk in chunks])

    data = run_with_client(collect)

    # Then the request follows from that origin and offset, and the bytes arrive
    assert dict(route.calls.last.request.url.params) == {
        "task": "app",
        "type": "stderr",
        "origin": "start",
        "offset": "8192",
        "plain": "true",
        "follow": "true",
    }
    assert data == b"line\n"


def test_read_log_reads_from_start(httpx2_mock: respx.Router):
    """Verify read_log reads the whole log from the start and returns its raw bytes."""
    # Given a mocked logs endpoint returning invalid UTF-8
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/a1").respond(content=b"ok \xff\n")

    # When reading the full stdout log
    content = run_with_client(
        lambda client: client.allocations.read_log("a1", task="app", stream="stdout")
    )

    # Then it reads from the start without following, and the bytes arrive unchanged
    params = route.calls.last.request.url.params
    assert params["origin"] == "start"
    assert params["offset"] == "0"
    assert params["follow"] == "false"
    assert params["plain"] == "true"
    assert content == b"ok \xff\n"
