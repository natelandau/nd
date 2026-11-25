"""Tests for the nodes resource."""

import httpx  # respx-bundled; used to build sequenced mock responses
import respx

from tests.builders import node_detail, node_stub, to_payload
from tests.helpers import NOMAD_TEST_ADDR, run_with_client


def test_list_paginates_and_decodes_stubs(httpx2_mock: respx.Router):
    """Verify nodes.list follows pagination and decodes every page into stubs."""
    # Given a two-page nodes listing, the first page carrying a next-token header
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/nodes").mock(
        side_effect=[
            httpx.Response(
                200, json=[to_payload(node_stub(node_id="n1"))], headers={"X-Nomad-Nexttoken": "t2"}
            ),
            httpx.Response(200, json=[to_payload(node_stub(node_id="n2"))]),
        ]
    )

    # When listing nodes
    nodes = run_with_client(lambda client: client.nodes.list())

    # Then both pages are decoded in order
    assert [n.id for n in nodes] == ["n1", "n2"]


def test_read_decodes_single_node(httpx2_mock: respx.Router):
    """Verify nodes.read decodes a single node including its metadata."""
    # Given a mocked single-node endpoint
    route = httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/node/n1").respond(
        json=to_payload(node_detail(node_id="n1", meta={"role": "web"})),
    )

    # When reading the node
    node = run_with_client(lambda client: client.nodes.read("n1"))

    # Then the metadata decodes and the expected path was called
    assert node.meta == {"role": "web"}
    assert route.calls.last.request.url.path == "/v1/node/n1"
