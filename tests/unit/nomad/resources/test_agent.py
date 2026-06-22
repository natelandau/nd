"""Tests for the agent resource."""

import asyncio

import respx

from nd.nomad.config import NomadConfig
from nd.nomad.models.agent import AgentSelf
from nd.nomad.resources.agent import AgentResource
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"


def test_agent_self_decodes_member(httpx2_mock: respx.Router):
    """Verify agent.self decodes the agent/self payload into AgentSelf."""
    # Given a mocked agent/self endpoint
    route = httpx2_mock.get(f"{_ADDR}/v1/agent/self").respond(
        json={"member": {"Name": "srv1", "Addr": "10.0.0.1", "Status": "alive"}},
    )
    resource = AgentResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When reading the agent's self info
    async def run() -> AgentSelf:
        result = await resource.self()
        await resource._transport.aclose()
        return result

    agent = asyncio.run(run())

    # Then the member is decoded and the expected path was called
    assert agent.member.name == "srv1"
    assert route.called
    assert route.calls.last.request.url.path == "/v1/agent/self"
