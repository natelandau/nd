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


def test_deployments_read_returns_deployment(httpx2_mock: respx.Router):
    """Verify deployments.read fetches a single deployment with health counts."""
    # Given a mocked single-deployment endpoint
    route = httpx2_mock.get(f"{_ADDR}/v1/deployment/d1").respond(
        json={
            "ID": "d1",
            "JobID": "web",
            "Status": "successful",
            "TaskGroups": {"app": {"DesiredTotal": 1, "HealthyAllocs": 1}},
        }
    )
    resource = DeploymentsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When reading the deployment
    async def run() -> object:
        result = await resource.read("d1")
        await resource._transport.aclose()
        return result

    dep = asyncio.run(run())

    # Then the deployment decodes with task group health counts
    assert dep.status == "successful"
    assert dep.task_groups["app"].healthy_allocs == 1
    assert route.calls.last.request.url.path == "/v1/deployment/d1"
