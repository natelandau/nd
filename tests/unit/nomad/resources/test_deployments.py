"""Tests for the deployments resource."""

import asyncio

import respx

from nd.nomad.config import NomadConfig
from nd.nomad.models.deployment import DeploymentListStub
from nd.nomad.resources.deployments import DeploymentsResource
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"
_STUB = {
    "ID": "dep-1",
    "JobID": "web",
    "Namespace": "default",
    "Status": "running",
    "JobVersion": 3,
    "CreateIndex": 1,
    "ModifyIndex": 2,
}


def test_deployments_list_decodes_stubs(httpx2_mock: respx.Router):
    """Verify deployments.list decodes the deployment listing into stubs."""
    # Given a mocked deployments endpoint
    route = httpx2_mock.get(f"{_ADDR}/v1/deployments").respond(json=[_STUB])
    resource = DeploymentsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When listing deployments
    async def run() -> list[DeploymentListStub]:
        result = await resource.list()
        await resource._transport.aclose()
        return result

    deployments = asyncio.run(run())

    # Then the stub decodes and the expected path was called
    assert [d.job_id for d in deployments] == ["web"]
    assert route.calls.last.request.url.path == "/v1/deployments"
