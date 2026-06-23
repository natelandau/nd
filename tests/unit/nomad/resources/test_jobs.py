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


_ALLOC = {
    "ID": "a1",
    "Name": "web.web[0]",
    "Namespace": "default",
    "NodeID": "n1",
    "JobID": "web",
    "TaskGroup": "web",
    "ClientStatus": "running",
    "DesiredStatus": "stop",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}


def test_stop_sends_delete_with_purge(httpx2_mock: respx.Router):
    """Verify jobs.stop issues a DELETE with purge=true and decodes the eval id."""
    # Given a mocked stop endpoint
    route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(
        json={"EvalID": "e1", "EvalCreateIndex": 3, "JobModifyIndex": 4}
    )
    resource = JobsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When stopping the job with purge
    async def run() -> object:
        result = await resource.stop("web", purge=True)
        await resource._transport.aclose()
        return result

    resp = asyncio.run(run())

    # Then the eval id decodes and purge is sent as a query param
    assert resp.eval_id == "e1"
    assert route.calls.last.request.url.path == "/v1/job/web"
    assert route.calls.last.request.url.params["purge"] == "true"


def test_stop_defaults_purge_false(httpx2_mock: respx.Router):
    """Verify jobs.stop sends purge=false by default."""
    # Given a mocked stop endpoint
    route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    resource = JobsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When stopping without purge
    async def run() -> None:
        await resource.stop("web")
        await resource._transport.aclose()

    asyncio.run(run())

    # Then purge is false
    assert route.calls.last.request.url.params["purge"] == "false"


def test_allocations_lists_job_allocations(httpx2_mock: respx.Router):
    """Verify jobs.allocations fetches and decodes a job's allocations."""
    # Given a mocked job-allocations endpoint
    route = httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[_ALLOC])
    resource = JobsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When listing the job's allocations
    async def run() -> list:
        result = await resource.allocations("web")
        await resource._transport.aclose()
        return result

    allocs = asyncio.run(run())

    # Then the allocation decodes and the expected path was called
    assert allocs[0].client_status == "running"
    assert route.calls.last.request.url.path == "/v1/job/web/allocations"


def test_jobs_register_posts_compiled_body(httpx2_mock: respx.Router):
    """Verify jobs.register POSTs the compiled job and decodes the eval id."""
    # Given a mocked register endpoint
    route = httpx2_mock.post(f"{_ADDR}/v1/jobs").respond(json={"EvalID": "e1", "JobModifyIndex": 7})
    resource = JobsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When registering a compiled job payload
    async def run() -> object:
        result = await resource.register(b'{"Job": {"ID": "web"}}')
        await resource._transport.aclose()
        return result

    resp = asyncio.run(run())

    # Then the eval id decodes and the expected path was called
    assert resp.eval_id == "e1"
    assert resp.job_modify_index == 7
    assert route.calls.last.request.url.path == "/v1/jobs"


_DEPLOY_STUB = {
    "ID": "d1",
    "JobID": "web",
    "Status": "running",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}


def test_jobs_deployments_lists_for_job(httpx2_mock: respx.Router):
    """Verify jobs.deployments lists a job's deployments."""
    # Given a mocked job-deployments endpoint
    route = httpx2_mock.get(f"{_ADDR}/v1/job/web/deployments").respond(json=[_DEPLOY_STUB])
    resource = JobsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When listing the job's deployments
    async def run() -> list:
        result = await resource.deployments("web")
        await resource._transport.aclose()
        return result

    deps = asyncio.run(run())

    # Then the stub decodes and the expected path was called
    assert [d.id for d in deps] == ["d1"]
    assert route.calls.last.request.url.path == "/v1/job/web/deployments"
