"""Tests for the NomadClient facade."""

import asyncio

import respx

from nd.nomad.client import NomadClient
from nd.nomad.config import NomadConfig
from tests.builders import agent_member, to_payload
from tests.helpers import NOMAD_TEST_ADDR, run_with_client


def test_client_round_trips_through_a_resource(httpx2_mock: respx.Router):
    """Verify NomadClient wires its transport so a resource call round-trips."""
    # Given a mocked agent/members endpoint
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/agent/members").respond(
        json={"Members": [to_payload(agent_member("srv1"))]},
    )

    # When calling a resource through the client's async context manager
    members = run_with_client(lambda client: client.agent.members())

    # Then the call succeeds and decodes
    assert [m.name for m in members] == ["srv1"]


def test_client_exposes_all_resource_namespaces():
    """Verify NomadClient exposes the agent, nodes, jobs, and allocations namespaces."""
    # Given a client built from explicit config
    client = NomadClient(config=NomadConfig(address=NOMAD_TEST_ADDR))

    # When inspecting its resource namespaces
    # Then all four are present
    assert hasattr(client, "agent")
    assert hasattr(client, "nodes")
    assert hasattr(client, "jobs")
    assert hasattr(client, "allocations")
    asyncio.run(client.aclose())
