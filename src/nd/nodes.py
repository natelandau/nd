"""Resolve Nomad node IDs to the names users recognize."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nd.nomad import NomadClient

# Enough of a node ID to tell nodes apart when the name is unknown.
_NODE_ID_PREFIX_LENGTH = 8


async def node_names_by_id(client: NomadClient) -> dict[str, str]:
    """Map node IDs to node names so output can show placement by name, not GUID.

    Fetch once per command run and share across every target, since the node roster
    does not change over the life of a single command.

    Args:
        client: An open Nomad API client.

    Returns:
        dict[str, str]: Node names keyed by node ID.
    """
    return {node.id: node.name for node in await client.nodes.list()}


def node_label(node_names: dict[str, str], node_id: str) -> str:
    """Name a node for display, falling back to a short ID for an unknown node.

    A node missing from ``node_names`` (recently removed, or never fetched) still
    renders as something readable instead of a full GUID.

    Args:
        node_names: Node names keyed by node ID, as from ``node_names_by_id``.
        node_id: The node to label.

    Returns:
        str: The node's name, or the first characters of its ID.
    """
    return node_names.get(node_id, node_id[:_NODE_ID_PREFIX_LENGTH])
