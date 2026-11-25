"""Tests for the async Nomad transport."""

import asyncio

import httpx  # respx-bundled; used to build sequenced mock responses
import httpx2
import pytest
import respx

from nd.nomad.config import NomadConfig
from nd.nomad.errors import (
    NomadAuthError,
    NomadConnectionError,
    NomadNotFoundError,
    NomadServerError,
)
from nd.nomad.transport import AsyncTransport
from tests.helpers import NOMAD_TEST_ADDR


def test_request_sends_token_and_merges_params(httpx2_mock: respx.Router):
    """Verify request sends the ACL token and merges default and call params."""
    # Given a configured transport and a mocked nodes endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/nodes").respond(json={"ok": True})
    config = NomadConfig(
        address=NOMAD_TEST_ADDR,
        token="secret",  # noqa: S106
        namespace="team-a",
        region="us",
    )
    transport = AsyncTransport(config)

    # When a request is made with an extra query param
    async def run() -> httpx2.Response:
        result = await transport.request("GET", "/nodes", params={"prefix": "ab"})
        await transport.aclose()
        return result

    resp = asyncio.run(run())

    # Then the response succeeds and the recorded request carries token and merged params
    assert resp.status_code == 200
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["X-Nomad-Token"] == "secret"
    assert sent.url.params["namespace"] == "team-a"
    assert sent.url.params["region"] == "us"
    assert sent.url.params["prefix"] == "ab"


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, NomadAuthError), (404, NomadNotFoundError), (500, NomadServerError)],
)
def test_request_maps_http_error_status(status, expected, httpx2_mock: respx.Router):
    """Verify non-2xx responses raise the matching typed error with context."""
    # Given an endpoint returning an error status
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/nodes").respond(status, text="nope")
    transport = AsyncTransport(NomadConfig(address=NOMAD_TEST_ADDR))

    # When the request is made
    async def run() -> None:
        try:
            await transport.request("GET", "/nodes")
        finally:
            await transport.aclose()

    # Then the mapped exception carries the status and path
    with pytest.raises(expected) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status_code == status
    assert exc_info.value.path == "/nodes"


def test_request_maps_transport_failure_to_connection_error(httpx2_mock: respx.Router):
    """Verify a transport failure becomes a NomadConnectionError."""
    # Given an endpoint that raises a connect error
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/nodes").mock(side_effect=httpx2.ConnectError("refused"))
    transport = AsyncTransport(NomadConfig(address=NOMAD_TEST_ADDR))

    # When the request is made
    async def run() -> None:
        try:
            await transport.request("GET", "/nodes")
        finally:
            await transport.aclose()

    # Then it surfaces as a NomadConnectionError
    with pytest.raises(NomadConnectionError):
        asyncio.run(run())


def test_paginate_follows_next_token(httpx2_mock: respx.Router):
    """Verify paginate yields each page until the next-token header is absent."""
    # Given an endpoint whose first page carries a next-token header
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/nodes").mock(
        side_effect=[
            httpx.Response(200, json=[1], headers={"X-Nomad-Nexttoken": "t2"}),
            httpx.Response(200, json=[2]),
        ]
    )
    transport = AsyncTransport(NomadConfig(address=NOMAD_TEST_ADDR))

    # When iterating all pages
    async def run() -> list[list[int]]:
        pages = [resp.json() async for resp in transport.paginate("/nodes")]
        await transport.aclose()
        return pages

    pages = asyncio.run(run())

    # Then both pages are yielded and the second call passed the next_token
    assert pages == [[1], [2]]
    assert route.call_count == 2
    assert route.calls.last.request.url.params["next_token"] == "t2"  # noqa: S105
