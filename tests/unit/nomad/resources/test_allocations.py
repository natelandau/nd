"""Tests for the allocations resource."""

import asyncio
import json

import respx

from nd.nomad.config import NomadConfig
from nd.nomad.models.allocation import AllocListStub
from nd.nomad.resources.allocations import AllocationsResource
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"
_STUB = {
    "ID": "a1",
    "Name": "web.web[0]",
    "Namespace": "default",
    "NodeID": "n1",
    "JobID": "web",
    "TaskGroup": "web",
    "ClientStatus": "running",
    "DesiredStatus": "run",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}


def test_list_decodes_allocations(httpx2_mock: respx.Router):
    """Verify allocations.list decodes the listing into stubs."""
    # Given a mocked allocations listing endpoint
    route = httpx2_mock.get(f"{_ADDR}/v1/allocations").respond(json=[_STUB])
    resource = AllocationsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When listing allocations
    async def run() -> list[AllocListStub]:
        result = await resource.list()
        await resource._transport.aclose()
        return result

    allocs = asyncio.run(run())

    # Then the irregular-cased node id decodes and the expected path was called
    assert allocs[0].node_id == "n1"
    assert route.calls.last.request.url.path == "/v1/allocations"


def test_signal_posts_signal_and_task(httpx2_mock: respx.Router):
    """Verify allocations.signal posts the signal and task name to the client endpoint."""
    # Given a mocked signal endpoint returning Nomad's empty object
    route = httpx2_mock.post(f"{_ADDR}/v1/client/allocation/a1/signal").respond(json={})
    resource = AllocationsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When signaling a named task
    async def run() -> None:
        await resource.signal("a1", signal="SIGUSR1", task="server")
        await resource._transport.aclose()

    asyncio.run(run())

    # Then the request carries both fields in Nomad's PascalCase form
    assert route.calls.last.request.url.path == "/v1/client/allocation/a1/signal"
    assert json.loads(route.calls.last.request.content) == {"Signal": "SIGUSR1", "Task": "server"}
