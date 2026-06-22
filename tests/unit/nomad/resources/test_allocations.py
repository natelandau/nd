"""Tests for the allocations resource."""

import asyncio

import respx

from nd.nomad.config import NomadConfig
from nd.nomad.models.allocation import Allocation, AllocListStub
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


def test_read_decodes_task_states(httpx2_mock: respx.Router):
    """Verify allocations.read decodes the per-task states map."""
    # Given a mocked single-allocation endpoint carrying task states
    httpx2_mock.get(f"{_ADDR}/v1/allocation/a1").respond(
        json={
            **_STUB,
            "TaskStates": {"server": {"State": "running", "Failed": False, "Restarts": 0}},
        },
    )
    resource = AllocationsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When reading the allocation
    async def run() -> Allocation:
        result = await resource.read("a1")
        await resource._transport.aclose()
        return result

    alloc = asyncio.run(run())

    # Then the task state decodes
    assert alloc.task_states["server"].state == "running"
