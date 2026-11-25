"""Tests for node ID to name resolution."""

from __future__ import annotations

import pytest

from nd.nodes import node_label


@pytest.mark.parametrize(
    ("node_id", "expected"),
    [
        pytest.param("abcdef12-3456-7890", "nas", id="known-node"),
        pytest.param("0123456789abcdef", "01234567", id="unknown-node-short-id"),
    ],
)
def test_node_label_names_known_nodes_and_shortens_unknown_ids(node_id, expected) -> None:
    """Verify a known node shows its name and an unknown node a short ID."""
    # Given a name map holding one node
    node_names = {"abcdef12-3456-7890": "nas"}

    # When labeling the node, Then the name or ID prefix is shown
    assert node_label(node_names=node_names, node_id=node_id) == expected
