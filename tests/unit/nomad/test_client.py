"""Tests for the NomadClient facade."""

import asyncio

import respx

from nd.nomad.client import NomadClient
from nd.nomad.config import NomadConfig

_ADDR = "http://nomad.test:4646"


def test_client_round_trips_through_a_resource(httpx2_mock: respx.Router):
    """Verify NomadClient wires its transport so a resource call round-trips."""
    # Given a mocked agent/self endpoint and a client from explicit config
    httpx2_mock.get(f"{_ADDR}/v1/agent/self").respond(
        json={"member": {"Name": "srv1", "Addr": "10.0.0.1", "Status": "alive"}},
    )

    # When calling a resource through the client's async context manager
    async def run() -> object:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await client.agent.self()

    agent = asyncio.run(run())

    # Then the call succeeds and decodes
    assert agent.member.name == "srv1"


def test_client_exposes_all_resource_namespaces():
    """Verify NomadClient exposes the agent, nodes, jobs, and allocations namespaces."""
    # Given a client built from explicit config
    client = NomadClient(config=NomadConfig(address=_ADDR))

    # When inspecting its resource namespaces
    # Then all four are present
    assert hasattr(client, "agent")
    assert hasattr(client, "nodes")
    assert hasattr(client, "jobs")
    assert hasattr(client, "allocations")
    asyncio.run(client.aclose())
