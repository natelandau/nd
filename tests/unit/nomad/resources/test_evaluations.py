"""Tests for the evaluations resource."""

import asyncio

import respx

from nd.nomad.config import NomadConfig
from nd.nomad.models.evaluation import EvalListStub
from nd.nomad.resources.evaluations import EvaluationsResource
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"
_STUB = {
    "ID": "eval-1",
    "JobID": "web",
    "Namespace": "default",
    "Status": "blocked",
    "Type": "service",
    "TriggeredBy": "job-register",
    "QueuedAllocations": {"web": 1},
    "CreateIndex": 1,
    "ModifyIndex": 2,
}


def test_evaluations_list_decodes_stubs(httpx2_mock: respx.Router):
    """Verify evaluations.list decodes the evaluation listing into stubs."""
    # Given a mocked evaluations endpoint
    route = httpx2_mock.get(f"{_ADDR}/v1/evaluations").respond(json=[_STUB])
    resource = EvaluationsResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When listing evaluations
    async def run() -> list[EvalListStub]:
        result = await resource.list()
        await resource._transport.aclose()
        return result

    evals = asyncio.run(run())

    # Then the stub decodes and the expected path was called
    assert [e.job_id for e in evals] == ["web"]
    assert evals[0].queued_allocations == {"web": 1}
    assert route.calls.last.request.url.path == "/v1/evaluations"
