"""Deployments resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.deployment import Deployment
from nd.nomad.resources.base import BaseResource


class DeploymentsResource(BaseResource):
    """Read access to Nomad deployments."""

    async def list(self) -> builtins.list[Deployment]:
        """List all deployments (``GET /v1/deployments``), following pagination."""
        return await self._paginate_list(path="/deployments", item_type=Deployment)
