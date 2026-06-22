"""Tests for the jobs resource."""

import asyncio

import respx

from nd.nomad.config import NomadConfig
from nd.nomad.resources.jobs import JobsResource
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"
_STUB = {
    "ID": "web",
    "Name": "web",
    "Type": "service",
    "Status": "running",
    "Priority": 50,
    "Namespace": "default",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}


def test_list_decodes_jobs(httpx2_mock: respx.Router):
    """Verify jobs.list decodes the jobs listing into stubs."""
    # Given a mocked jobs listing endpoint
    route = httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_STUB])
    resource = JobsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When listing jobs
    async def run() -> list:
        result = await resource.list()
        await resource._transport.aclose()
        return result

    jobs = asyncio.run(run())

    # Then the stub is decoded and the expected path was called
    assert jobs[0].id == "web"
    assert route.calls.last.request.url.path == "/v1/jobs"


def test_read_decodes_single_job(httpx2_mock: respx.Router):
    """Verify jobs.read decodes a single job with its datacenters."""
    # Given a mocked single-job endpoint
    httpx2_mock.get(f"{_ADDR}/v1/job/web").respond(json={**_STUB, "Datacenters": ["dc1"]})
    resource = JobsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When reading the job
    async def run() -> object:
        result = await resource.read("web")
        await resource._transport.aclose()
        return result

    job = asyncio.run(run())

    # Then the datacenters list decodes
    assert job.datacenters == ["dc1"]
