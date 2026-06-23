"""Tests for the status resource."""

import asyncio

import respx

from nd.nomad.config import NomadConfig
from nd.nomad.resources.status import StatusResource
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"


def test_status_leader_decodes_string(httpx2_mock: respx.Router):
    """Verify status.leader decodes the leader RPC address string."""
    # Given a mocked status/leader endpoint returning a JSON string
    route = httpx2_mock.get(f"{_ADDR}/v1/status/leader").respond(json="10.0.0.1:4647")
    resource = StatusResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When reading the leader
    async def run() -> str:
        result = await resource.leader()
        await resource._transport.aclose()
        return result

    leader = asyncio.run(run())

    # Then the address decodes and the expected path was called
    assert leader == "10.0.0.1:4647"
    assert route.calls.last.request.url.path == "/v1/status/leader"
