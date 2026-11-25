"""Tests for the agent resource."""

import respx

from tests.builders import agent_member, to_payload
from tests.helpers import NOMAD_TEST_ADDR, run_with_client


def test_agent_members_decodes_server_list(httpx2_mock: respx.Router):
    """Verify agent.members decodes the server membership list with tags."""
    # Given a mocked agent/members endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/agent/members").respond(
        json={"Members": [to_payload(agent_member("mf1.global", build="2.0.3"))]},
    )

    # When listing server members
    members = run_with_client(lambda client: client.agent.members())

    # Then the member and its tags decode and the expected path was called
    assert [m.name for m in members] == ["mf1.global"]
    assert members[0].tags["build"] == "2.0.3"
    assert route.calls.last.request.url.path == "/v1/agent/members"
