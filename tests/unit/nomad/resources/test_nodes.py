"""Tests for the nodes resource."""

import asyncio

import httpx  # respx-bundled; used to build sequenced mock responses
import respx

from nd.nomad.config import NomadConfig
from nd.nomad.models.node import Node, NodeListStub
from nd.nomad.resources.nodes import NodesResource
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"
_STUB = {
    "ID": "n1",
    "Datacenter": "dc1",
    "Name": "client-1",
    "NodeClass": "",
    "NodePool": "default",
    "Drain": False,
    "SchedulingEligibility": "eligible",
    "Status": "ready",
    "Version": "1.9.0",
    "CreateIndex": 1,
    "ModifyIndex": 2,
}


def test_list_paginates_and_decodes_stubs(httpx2_mock: respx.Router):
    """Verify nodes.list follows pagination and decodes every page into stubs."""
    # Given a two-page nodes listing, the first page carrying a next-token header
    httpx2_mock.get(f"{_ADDR}/v1/nodes").mock(
        side_effect=[
            httpx.Response(200, json=[_STUB], headers={"X-Nomad-Nexttoken": "t2"}),
            httpx.Response(200, json=[{**_STUB, "ID": "n2"}]),
        ]
    )
    resource = NodesResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When listing nodes
    async def run() -> list[NodeListStub]:
        result = await resource.list()
        await resource._transport.aclose()
        return result

    nodes = asyncio.run(run())

    # Then both pages are decoded in order
    assert [n.id for n in nodes] == ["n1", "n2"]


def test_read_decodes_single_node(httpx2_mock: respx.Router):
    """Verify nodes.read decodes a single node including irregular-key fields."""
    # Given a mocked single-node endpoint
    route = httpx2_mock.get(f"{_ADDR}/v1/node/n1").respond(
        json={**_STUB, "HTTPAddr": "10.0.0.5:4646", "TLSEnabled": False},
    )
    resource = NodesResource(AsyncTransport(NomadConfig(address=_ADDR)))

    # When reading the node
    async def run() -> Node:
        result = await resource.read("n1")
        await resource._transport.aclose()
        return result

    node = asyncio.run(run())

    # Then the irregular-cased field decodes and the expected path was called
    assert node.http_addr == "10.0.0.5:4646"
    assert route.calls.last.request.url.path == "/v1/node/n1"
