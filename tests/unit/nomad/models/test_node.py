"""Tests for node models."""

import msgspec

from nd.nomad.models.node import Node, NodeListStub


def test_node_list_stub_decodes():
    """Verify NodeListStub decodes a node listing stub and tolerates unknown keys."""
    # Given a node-list stub payload with an unknown extra key
    payload = b"""
    {
      "ID": "abc-123", "Datacenter": "dc1", "Name": "client-1",
      "NodeClass": "", "NodePool": "default", "Drain": false,
      "Address": "10.0.0.7",
      "SchedulingEligibility": "eligible", "Status": "ready",
      "Version": "1.9.0", "CreateIndex": 10, "ModifyIndex": 42,
      "Unknown": "ignored"
    }
    """
    # When decoding the payload
    stub = msgspec.json.decode(payload, type=NodeListStub)
    # Then the typed fields are populated
    assert stub.id == "abc-123"
    assert stub.status == "ready"
    assert stub.address == "10.0.0.7"
    assert stub.modify_index == 42


def test_node_decodes_irregular_keys():
    """Verify Node decodes and maps irregular key names correctly."""
    # Given a node payload with irregular pascal-case keys
    payload = b"""
    {
      "ID": "abc-123", "Datacenter": "dc1", "Name": "client-1",
      "NodeClass": "", "NodePool": "default", "Status": "ready",
      "Drain": false, "SchedulingEligibility": "eligible",
      "HTTPAddr": "10.0.0.5:4646", "TLSEnabled": true,
      "Attributes": {"os.name": "ubuntu"}, "Meta": {"role": "web"},
      "CreateIndex": 10, "ModifyIndex": 42
    }
    """
    # When decoding the node payload
    node = msgspec.json.decode(payload, type=Node)
    # Then the irregular keys are mapped to snake_case attributes
    assert node.http_addr == "10.0.0.5:4646"
    assert node.tls_enabled is True
    assert node.attributes["os.name"] == "ubuntu"
