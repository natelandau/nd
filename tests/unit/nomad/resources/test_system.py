"""Tests for the system resource."""

from collections.abc import Awaitable, Callable

import pytest
import respx

from nd.nomad import NomadClient
from tests.helpers import NOMAD_TEST_ADDR, run_with_client


@pytest.mark.parametrize(
    ("call", "path"),
    [
        pytest.param(lambda client: client.system.gc(), "/v1/system/gc", id="gc"),
        pytest.param(
            lambda client: client.system.reconcile_summaries(),
            "/v1/system/reconcile/summaries",
            id="reconcile-summaries",
        ),
    ],
)
def test_system_operation_sends_put(
    httpx2_mock: respx.Router, call: Callable[[NomadClient], Awaitable[None]], path: str
):
    """Verify each system operation issues a PUT to its endpoint and returns None."""
    # Given a mocked system endpoint returning an empty 200
    route = httpx2_mock.put(f"{NOMAD_TEST_ADDR}{path}").respond(status_code=200)

    # When running the operation
    result = run_with_client(call)

    # Then nothing is returned and the expected path/method was called
    assert result is None
    assert route.calls.last.request.method == "PUT"
    assert route.calls.last.request.url.path == path
