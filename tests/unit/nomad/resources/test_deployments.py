"""Tests for the deployments resource."""

import respx

from tests.builders import deployment, to_payload
from tests.helpers import NOMAD_TEST_ADDR, run_with_client


def test_deployments_list_decodes_stubs(httpx2_mock: respx.Router):
    """Verify deployments.list decodes the deployment listing into deployments."""
    # Given a mocked deployments endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/deployments").respond(
        json=[to_payload(deployment("web", job_version=3))]
    )

    # When listing deployments
    deployments = run_with_client(lambda client: client.deployments.list())

    # Then the stub decodes and the expected path was called
    assert [d.job_id for d in deployments] == ["web"]
    assert route.calls.last.request.url.path == "/v1/deployments"
