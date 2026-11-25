"""Tests for the evaluations resource."""

import respx

from tests.builders import eval_stub, to_payload
from tests.helpers import NOMAD_TEST_ADDR, run_with_client


def test_evaluations_list_decodes_stubs(httpx2_mock: respx.Router):
    """Verify evaluations.list decodes the evaluation listing into stubs."""
    # Given a mocked evaluations endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/evaluations").respond(
        json=[to_payload(eval_stub("web", status="blocked", queued={"web": 1}))]
    )

    # When listing evaluations
    evals = run_with_client(lambda client: client.evaluations.list())

    # Then the stub decodes and the expected path was called
    assert [e.job_id for e in evals] == ["web"]
    assert evals[0].queued_allocations == {"web": 1}
    assert route.calls.last.request.url.path == "/v1/evaluations"
