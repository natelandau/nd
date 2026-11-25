"""Tests for the status resource."""

import respx

from tests.helpers import NOMAD_TEST_ADDR, run_with_client


def test_status_leader_decodes_string(httpx2_mock: respx.Router):
    """Verify status.leader decodes the leader RPC address string."""
    # Given a mocked status/leader endpoint returning a JSON string
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/status/leader").respond(json="10.0.0.1:4647")

    # When reading the leader
    leader = run_with_client(lambda client: client.status.leader())

    # Then the address decodes and the expected path was called
    assert leader == "10.0.0.1:4647"
    assert route.calls.last.request.url.path == "/v1/status/leader"
