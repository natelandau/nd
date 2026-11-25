"""Tests for the allocations resource."""

import json

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
