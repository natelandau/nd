"""Tests for the async Nomad transport."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx  # respx-bundled; used to build sequenced mock responses
import httpx2
import pytest
import respx

from nd.nomad.config import NomadConfig
from nd.nomad.errors import (
    NomadAuthError,
    NomadConnectionError,
    NomadDecodeError,
    NomadNotFoundError,
    NomadServerError,
)
from nd.nomad.transport import AsyncTransport, _build_client_cert
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


def test_request_timeout_overrides_client_timeout(httpx2_mock: respx.Router):
    """Verify a per-request timeout replaces the configured one for that request only."""
    # Given a transport configured with a 5-second timeout
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/nodes").respond(json=[])
    transport = AsyncTransport(NomadConfig(address=NOMAD_TEST_ADDR, timeout=5.0))

    # When one request asks for 40 seconds and the next asks for nothing
    async def run() -> None:
        await transport.request("GET", "/nodes", request_timeout=40.0)
        await transport.request("GET", "/nodes")
        await transport.aclose()

    asyncio.run(run())

    # Then only the first request carries the longer read timeout
    reads = [call.request.extensions["timeout"]["read"] for call in route.calls]
    assert reads == [40.0, 5.0]


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


async def _request_once(transport: AsyncTransport) -> None:
    await transport.request("GET", "/nodes")


async def _stream_once(transport: AsyncTransport) -> None:
    async with transport.stream("GET", "/nodes") as chunks:
        async for _chunk in chunks:
            pass


@pytest.mark.parametrize("call", [_request_once, _stream_once], ids=["request", "stream"])
def test_transport_failure_maps_to_connection_error(
    call: Callable[[AsyncTransport], Awaitable[None]], httpx2_mock: respx.Router
):
    """Verify a transport failure becomes a NomadConnectionError for requests and streams."""
    # Given an endpoint that raises a connect error
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/nodes").mock(side_effect=httpx2.ConnectError("refused"))
    transport = AsyncTransport(NomadConfig(address=NOMAD_TEST_ADDR))

    # When the request is made
    async def run() -> None:
        try:
            await call(transport)
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


@pytest.mark.parametrize(
    ("cert", "cert_key", "expected"),
    [
        pytest.param("/c.pem", "/k.pem", ("/c.pem", "/k.pem"), id="cert-and-key"),
        pytest.param("/both.pem", None, "/both.pem", id="combined-cert"),
        pytest.param(None, None, None, id="no-mtls"),
    ],
)
def test_build_client_cert_pairs_cert_with_key(
    cert: str | None, cert_key: str | None, expected: tuple[str, str] | str | None
):
    """Verify mutual TLS sends the cert with its key, or a combined cert file alone."""
    # Given a config with the client certificate settings
    config = NomadConfig(address=NOMAD_TEST_ADDR, client_cert=cert, client_key=cert_key)

    # When building the client certificate argument
    # Then a key is paired with its cert, and a lone cert is passed as a combined file
    assert _build_client_cert(config) == expected


def test_stream_yields_chunks(httpx2_mock: respx.Router):
    """Verify stream yields the response body chunks as they arrive."""

    # Given an endpoint streaming a body in two chunks
    async def body() -> AsyncIterator[bytes]:
        yield b"hello "
        yield b"world"

    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/logs").mock(
        return_value=httpx.Response(200, content=body())
    )
    transport = AsyncTransport(NomadConfig(address=NOMAD_TEST_ADDR))

    # When streaming the endpoint
    async def run() -> bytes:
        async with transport.stream("GET", "/logs") as chunks:
            data = b"".join([chunk async for chunk in chunks])
        await transport.aclose()
        return data

    # Then the joined chunks equal the body
    assert asyncio.run(run()) == b"hello world"


def test_stream_raises_not_found_on_404(httpx2_mock: respx.Router):
    """Verify stream raises the same typed error as request on a non-2xx response."""
    # Given an endpoint returning 404
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/logs").respond(404, text="gone")
    transport = AsyncTransport(NomadConfig(address=NOMAD_TEST_ADDR))

    # When streaming it
    async def run() -> None:
        try:
            async with transport.stream("GET", "/logs"):
                pass
        finally:
            await transport.aclose()

    # Then NomadNotFoundError is raised
    with pytest.raises(NomadNotFoundError):
        asyncio.run(run())


@pytest.mark.parametrize(
    ("header", "expected_index"),
    [
        pytest.param("42", 42, id="index-from-header"),
        pytest.param("0", 1, id="zero-raised-to-one"),
    ],
)
def test_blocking_request_returns_next_index(
    httpx2_mock: respx.Router, header: str, expected_index: int
):
    """Verify a blocking query sends its index and wait, and returns the index to pass next."""
    # Given an endpoint that answers with the given index header
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/things").respond(
        json=[], headers={"X-Nomad-Index": header}
    )
    transport = AsyncTransport(NomadConfig(address=NOMAD_TEST_ADDR, timeout=5.0))

    # When querying from index 7 with a 30-second wait
    async def run() -> int:
        _response, index = await transport.blocking_request("/things", index=7, wait_seconds=30)
        await transport.aclose()
        return index

    index = asyncio.run(run())

    # Then the query blocked on index 7 with a timeout longer than the wait, and a zero index
    # never comes back, so the next query cannot return at once
    assert index == expected_index
    request = route.calls.last.request
    assert (request.url.params["index"], request.url.params["wait"]) == ("7", "30s")
    assert request.extensions["timeout"]["read"] > 30


def test_blocking_request_rejects_a_missing_index(httpx2_mock: respx.Router):
    """Verify a blocking query whose response has no index header fails to decode."""
    # Given an endpoint that sends no X-Nomad-Index header
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/things").respond(json=[])
    transport = AsyncTransport(NomadConfig(address=NOMAD_TEST_ADDR))

    async def run() -> None:
        try:
            await transport.blocking_request("/things", index=0, wait_seconds=30)
        finally:
            await transport.aclose()

    # When querying, then a decode error names the header
    with pytest.raises(NomadDecodeError, match="X-Nomad-Index"):
        asyncio.run(run())
