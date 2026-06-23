"""Tests for the system resource."""

import asyncio

import respx

from nd.nomad.config import NomadConfig
from nd.nomad.resources.system import SystemResource
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"


def test_gc_sends_put_to_system_gc(httpx2_mock: respx.Router):
    """Verify system.gc issues a PUT to /v1/system/gc and returns None."""
    # Given a mocked force-GC endpoint returning an empty 200
    route = httpx2_mock.put(f"{_ADDR}/v1/system/gc").respond(status_code=200)
    resource = SystemResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When forcing garbage collection
    async def run() -> None:
        result = await resource.gc()
        await resource._transport.aclose()
        return result

    result = asyncio.run(run())

    # Then nothing is returned and the expected path/method was called
    assert result is None
    assert route.calls.last.request.method == "PUT"
    assert route.calls.last.request.url.path == "/v1/system/gc"


def test_reconcile_summaries_sends_put(httpx2_mock: respx.Router):
    """Verify system.reconcile_summaries issues a PUT and returns None."""
    # Given a mocked reconcile-summaries endpoint returning an empty 200
    route = httpx2_mock.put(f"{_ADDR}/v1/system/reconcile/summaries").respond(status_code=200)
    resource = SystemResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When reconciling job summaries
    async def run() -> None:
        result = await resource.reconcile_summaries()
        await resource._transport.aclose()
        return result

    result = asyncio.run(run())

    # Then nothing is returned and the expected path/method was called
    assert result is None
    assert route.calls.last.request.method == "PUT"
    assert route.calls.last.request.url.path == "/v1/system/reconcile/summaries"
