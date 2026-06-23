"""Nodes resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.node import Node, NodeListStub
from nd.nomad.resources.base import BaseResource


class NodesResource(BaseResource):
    """Read access to Nomad client nodes."""

    async def list(self) -> builtins.list[NodeListStub]:
        """List all nodes (``GET /v1/nodes``), following pagination."""
        return await self._paginate_list("/nodes", NodeListStub)

    async def read(self, node_id: str) -> Node:
        """Read a single node (``GET /v1/node/:id``)."""
        response = await self._transport.request("GET", f"/node/{node_id}")
        return self._decode(response, Node)
