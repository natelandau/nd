"""Tests for the allocations resource."""

import json

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


def test_restart_rejects_a_task_with_all_tasks(httpx2_mock: respx.Router):
    """Verify asking for one task and every task at once fails before any request."""
    # Given a reachable cluster
    # When restarting with both a task and all_tasks
    # Then it raises without contacting Nomad
    with pytest.raises(ValueError, match="not both"):
        run_with_client(
            lambda client: client.allocations.restart("a1", task="server", all_tasks=True)
        )
    assert not httpx2_mock.calls


def test_log_tail_reads_plain_text_from_the_end(httpx2_mock: respx.Router):
    """Verify allocations.log_tail asks for the stream's end as plain text and returns it."""
    # Given a mocked logs endpoint returning plain text
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/a1").respond(text="boom\n")

    # When reading the end of a task's stderr
    text = run_with_client(
        lambda client: client.allocations.log_tail(
            "a1", task="server", stream="stderr", max_bytes=1024
        )
    )

    # Then the request reads the stream from the end without following, as plain text
    params = route.calls.last.request.url.params
    assert dict(params) == {
        "task": "server",
        "type": "stderr",
        "origin": "end",
        "offset": "1024",
        "plain": "true",
        "follow": "false",
    }
    assert text == "boom\n"
