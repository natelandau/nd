"""Tests for the volumes resource."""

import asyncio
import json

import respx

from nd.nomad.config import NomadConfig
from nd.nomad.resources.volumes import VolumesResource
from nd.nomad.transport import AsyncTransport

_ADDR = "http://nomad.test:4646"
_VOL = {
    "ID": "data:abc",
    "Name": "data",
    "Namespace": "default",
    "NodeID": "n1",
    "NodePool": "default",
    "PluginID": "",
    "State": "ready",
}


def _resource() -> VolumesResource:
    return VolumesResource(AsyncTransport(NomadConfig(address=_ADDR)))


def test_list_filters_by_host_type(httpx2_mock: respx.Router):
    """Verify volumes.list requests type=host and decodes the listing."""
    # Given a mocked host-volume listing
    route = httpx2_mock.get(f"{_ADDR}/v1/volumes").respond(json=[_VOL])
    resource = _resource()

    # When listing
    async def run() -> list:
        result = await resource.list()
        await resource._transport.aclose()
        return result

    vols = asyncio.run(run())

    # Then the stub decodes and the type=host query param was sent
    assert vols[0].name == "data"
    assert vols[0].node_id == "n1"
    assert route.calls.last.request.url.params["type"] == "host"


def test_register_puts_volume_body(httpx2_mock: respx.Router):
    """Verify volumes.register PUTs the wrapped Volume body to the register endpoint."""
    # Given a mocked register endpoint
    route = httpx2_mock.put(f"{_ADDR}/v1/volume/host/register").respond(
        json={"Volume": _VOL, "Warnings": None}
    )
    resource = _resource()
    body = {"Name": "data", "Type": "host", "NodeID": "n1", "HostPath": "/srv/data"}

    # When registering
    async def run() -> object:
        result = await resource.register(body)
        await resource._transport.aclose()
        return result

    resp = asyncio.run(run())

    # Then the request wraps the volume under a "Volume" key
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"Volume": body}
    assert resp.volume["Name"] == "data"


def test_delete_issues_delete_to_host_endpoint(httpx2_mock: respx.Router):
    """Verify volumes.delete issues DELETE to the host-volume delete endpoint."""
    # Given a mocked delete endpoint
    route = httpx2_mock.delete(f"{_ADDR}/v1/volume/host/data:abc/delete").respond(json={})
    resource = _resource()

    # When deleting
    async def run() -> None:
        await resource.delete("data:abc")
        await resource._transport.aclose()

    asyncio.run(run())

    # Then the delete endpoint was called
    assert route.called
    assert route.calls.last.request.url.path == "/v1/volume/host/data:abc/delete"
