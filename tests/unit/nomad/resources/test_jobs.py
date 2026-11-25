"""Tests for the jobs resource."""

import pytest
import respx

from tests.builders import alloc_stub, deployment, job_spec, job_stub, to_payload
from tests.helpers import NOMAD_TEST_ADDR, run_with_client


def test_list_decodes_jobs(httpx2_mock: respx.Router):
    """Verify jobs.list decodes the jobs listing into stubs."""
    # Given a mocked jobs listing endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=[to_payload(job_stub("web"))]
    )

    # When listing jobs
    jobs = run_with_client(lambda client: client.jobs.list())

    # Then the stub is decoded and the expected path was called
    assert jobs[0].id == "web"
    assert route.calls.last.request.url.path == "/v1/jobs"


def test_stop_sends_delete_and_decodes_eval_id(httpx2_mock: respx.Router):
    """Verify jobs.stop issues a DELETE to the job and decodes the eval id."""
    # Given a mocked stop endpoint
    route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(
        json={"EvalID": "e1", "EvalCreateIndex": 3, "JobModifyIndex": 4}
    )

    # When stopping the job with purge
    resp = run_with_client(lambda client: client.jobs.stop("web", purge=True))

    # Then the eval id decodes and the job path was called
    assert resp.eval_id == "e1"
    assert route.calls.last.request.url.path == "/v1/job/web"


@pytest.mark.parametrize(
    ("stop_kwargs", "expected_params"),
    [
        pytest.param({}, {"purge": "false", "no_shutdown_delay": "false"}, id="defaults"),
        pytest.param({"purge": True}, {"purge": "true"}, id="purge"),
        pytest.param(
            {"no_shutdown_delay": True}, {"no_shutdown_delay": "true"}, id="no-shutdown-delay"
        ),
    ],
)
def test_stop_sends_flags_as_query_params(
    httpx2_mock: respx.Router, stop_kwargs: dict[str, bool], expected_params: dict[str, str]
):
    """Verify jobs.stop forwards purge and no_shutdown_delay as query params, both off by default."""
    # Given a mocked stop endpoint
    route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})

    # When stopping the job with the given flags
    run_with_client(lambda client: client.jobs.stop("web", **stop_kwargs))

    # Then each flag is sent with the expected value
    sent_params = route.calls.last.request.url.params
    for name, value in expected_params.items():
        assert sent_params[name] == value


def test_allocations_lists_job_allocations(httpx2_mock: respx.Router):
    """Verify jobs.allocations fetches and decodes a job's allocations."""
    # Given a mocked job-allocations endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/allocations").respond(
        json=[to_payload(alloc_stub(job_id="web", client_status="running", desired_status="stop"))]
    )

    # When listing the job's allocations
    allocs = run_with_client(lambda client: client.jobs.allocations("web"))

    # Then the allocation decodes and the expected path was called
    assert allocs[0].client_status == "running"
    assert route.calls.last.request.url.path == "/v1/job/web/allocations"


def test_jobs_register_posts_compiled_body(httpx2_mock: respx.Router):
    """Verify jobs.register POSTs the compiled job bytes unchanged and decodes the eval id."""
    # Given a mocked register endpoint
    route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json={"EvalID": "e1", "JobModifyIndex": 7}
    )
    body = b'{"Job": {"ID": "web"}}'

    # When registering a compiled job payload
    resp = run_with_client(lambda client: client.jobs.register(body))

    # Then the body is sent as JSON byte for byte and the eval id decodes
    sent = route.calls.last.request
    assert sent.url.path == "/v1/jobs"
    assert sent.content == body
    assert sent.headers["Content-Type"] == "application/json"
    assert resp.eval_id == "e1"
    assert resp.job_modify_index == 7


def test_jobs_deployments_lists_for_job(httpx2_mock: respx.Router):
    """Verify jobs.deployments lists a job's deployments."""
    # Given a mocked job-deployments endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web/deployments").respond(
        json=[to_payload(deployment("web"))]
    )

    # When listing the job's deployments
    deps = run_with_client(lambda client: client.jobs.deployments("web"))

    # Then the deployment decodes and the expected path was called
    assert [d.id for d in deps] == ["dep-web"]
    assert route.calls.last.request.url.path == "/v1/job/web/deployments"


def test_get_decodes_job_spec(httpx2_mock: respx.Router):
    """Verify jobs.get fetches one job and decodes its full spec."""
    # Given a mocked job endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(
        json=to_payload(job_spec("web"))
    )

    # When fetching the job
    spec = run_with_client(lambda client: client.jobs.get("web"))

    # Then the spec is decoded from the job's own path
    assert spec.name == "web"
    assert spec.task_groups[0].tasks[0].config["image"] == "nginx:1.27"
    assert route.calls.last.request.url.path == "/v1/job/web"


def test_get_queries_the_job_namespace(httpx2_mock: respx.Router):
    """Verify jobs.get looks the job up in the namespace it was listed from."""
    # Given a mocked job endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/web").respond(
        json=to_payload(job_spec("web"))
    )

    # When fetching the job from a named namespace
    run_with_client(lambda client: client.jobs.get("web", namespace="media"))

    # Then the request names that namespace
    assert route.calls.last.request.url.params["namespace"] == "media"
