"""Tests for the volumes resource."""

import json

import httpx  # respx-bundled; used to build sequenced mock responses
import respx

from tests.builders import host_volume_stub, to_payload
from tests.helpers import NOMAD_TEST_ADDR, run_with_client


def test_list_paginates_with_host_type(httpx2_mock: respx.Router):
    """Verify volumes.list follows pagination and requests type=host on every page."""
    # Given a two-page host-volume listing
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/volumes").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[to_payload(host_volume_stub(volume_id="data:abc"))],
                headers={"X-Nomad-Nexttoken": "t2"},
            ),
            httpx.Response(200, json=[to_payload(host_volume_stub(volume_id="v2"))]),
        ]
    )

    # When listing
    vols = run_with_client(lambda client: client.volumes.list())

    # Then both pages decode and every request carried the type=host filter
    assert [v.id for v in vols] == ["data:abc", "v2"]
    assert all(call.request.url.params["type"] == "host" for call in route.calls)


def test_register_puts_volume_body(httpx2_mock: respx.Router):
    """Verify volumes.register PUTs the wrapped Volume body to the register endpoint."""
    # Given a mocked register endpoint
    route = httpx2_mock.put(f"{NOMAD_TEST_ADDR}/v1/volume/host/register").respond(
        json={"Volume": to_payload(host_volume_stub()), "Warnings": None}
    )
    body = {"Name": "data", "Type": "host", "NodeID": "n1", "HostPath": "/srv/data"}

    # When registering
    run_with_client(lambda client: client.volumes.register(body))

    # Then the request wraps the volume under a "Volume" key
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"Volume": body}


def test_delete_issues_delete_to_host_endpoint(httpx2_mock: respx.Router):
    """Verify volumes.delete issues DELETE to the host-volume delete endpoint."""
    # Given a mocked delete endpoint
    route = httpx2_mock.delete(f"{NOMAD_TEST_ADDR}/v1/volume/host/data:abc/delete").respond(json={})

    # When deleting
    run_with_client(lambda client: client.volumes.delete("data:abc"))

    # Then the delete endpoint was called
    assert route.called
    assert route.calls.last.request.url.path == "/v1/volume/host/data:abc/delete"
