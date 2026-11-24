"""Tests for the volumes resource."""

import asyncio
import json

import httpx  # respx-bundled; used to build sequenced mock responses
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


def test_list_paginates_with_host_type(httpx2_mock: respx.Router):
    """Verify volumes.list follows pagination and requests type=host on every page."""
    # Given a two-page host-volume listing
    route = httpx2_mock.get(f"{_ADDR}/v1/volumes").mock(
        side_effect=[
            httpx.Response(200, json=[_VOL], headers={"X-Nomad-Nexttoken": "t2"}),
            httpx.Response(200, json=[{**_VOL, "ID": "v2"}]),
        ]
    )
    resource = _resource()

    # When listing
    async def run() -> list:
        result = await resource.list()
        await resource._transport.aclose()
        return result

    vols = asyncio.run(run())

    # Then both pages decode and every request carried the type=host filter
    assert [v.id for v in vols] == [_VOL["ID"], "v2"]
    assert all(call.request.url.params["type"] == "host" for call in route.calls)


def test_register_puts_volume_body(httpx2_mock: respx.Router):
    """Verify volumes.register PUTs the wrapped Volume body to the register endpoint."""
    # Given a mocked register endpoint
    route = httpx2_mock.put(f"{_ADDR}/v1/volume/host/register").respond(
        json={"Volume": _VOL, "Warnings": None}
    )
    resource = _resource()
    body = {"Name": "data", "Type": "host", "NodeID": "n1", "HostPath": "/srv/data"}

    # When registering
    async def run() -> None:
        await resource.register(body)
        await resource._transport.aclose()

    asyncio.run(run())

    # Then the request wraps the volume under a "Volume" key
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"Volume": body}


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
