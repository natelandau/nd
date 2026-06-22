"""Tests for transport pagination."""

import asyncio

import httpx  # respx-bundled; used to build sequenced mock responses
import respx

from nd.nomad.config import NomadConfig
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"


def test_paginate_follows_next_token(httpx2_mock: respx.Router):
    """Verify paginate yields each page until the next-token header is absent."""
    # Given an endpoint whose first page carries a next-token header
    route = httpx2_mock.get(f"{_ADDR}/v1/nodes").mock(
        side_effect=[
            httpx.Response(200, json=[1], headers={"X-Nomad-Nexttoken": "t2"}),
            httpx.Response(200, json=[2]),
        ]
    )
    transport = AsyncTransport(NomadConfig(address=_ADDR))

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
