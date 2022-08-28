# type: ignore
"""Test Nomad job functions and classes."""

from nd._utils.cluster_nodes import Node, populate_nodes

mock_response = [
    {
        "Name": "node1",
        "ID": "00000000-0000-0000-0000-000000000000",
        "Address": "10.1.1.1",
        "Status": "ready",
        "SchedulingEligibility": "eligible",
        "Datacenter": "global",
        "NodeClass": "linux",
        "Version": "10.3.3",
    },
    {
        "Name": "node2",
        "ID": "00000000-0000-0000-0000-000000000000",
        "Address": "10.1.1.2",
        "Status": "ready",
        "SchedulingEligibility": "eligible",
        "Datacenter": "global",
        "NodeClass": "linux",
        "Version": "10.3.3",
    },
]


def test_node_class() -> None:
    """Test the Node class."""
    nodes = [
        Node(
            node["Name"],
            node["ID"],
            node["Address"],
            node["Status"],
            node["SchedulingEligibility"],
            node["Datacenter"],
            node["NodeClass"],
            node["Version"],
        )
        for node in mock_response
    ]

    assert nodes[0].name == "node1"
    assert nodes[0].id_num == "00000000-0000-0000-0000-000000000000"
    assert nodes[0].id_short == "00000000"
    assert nodes[0].address == "10.1.1.1"
    assert nodes[0].status == "ready"
    assert nodes[0].eligible == "eligible"
    assert nodes[0].datacenter == "global"
    assert nodes[0].node_class == "linux"
    assert nodes[0].version == "10.3.3"
    assert nodes[1].name == "node2"


def test_populate_nodes(mocker) -> None:
    """Test the populate_nodes function."""
    mocker.patch("nd._utils.cluster_nodes.make_nomad_api_call", return_value=mock_response)

    nodes = populate_nodes("http://junk.url")
    assert nodes[0].name == "node1"
    assert nodes[0].id_num == "00000000-0000-0000-0000-000000000000"
    assert nodes[0].id_short == "00000000"
    assert nodes[0].address == "10.1.1.1"
    assert nodes[0].status == "ready"
    assert nodes[0].eligible == "eligible"
    assert nodes[0].datacenter == "global"
    assert nodes[0].node_class == "linux"
    assert nodes[0].version == "10.3.3"
    assert nodes[1].name == "node2"
