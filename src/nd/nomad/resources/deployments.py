"""Deployments resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.deployment import Deployment, DeploymentListStub
from nd.nomad.resources.base import BaseResource


class DeploymentsResource(BaseResource):
    """Read access to Nomad deployments."""

    async def list(self) -> builtins.list[DeploymentListStub]:
        """List all deployments (``GET /v1/deployments``), following pagination."""
        return await self._paginate_list("/deployments", DeploymentListStub)

    async def read(self, deployment_id: str) -> Deployment:
        """Read a single deployment (``GET /v1/deployment/:id``).

        Fetch the full deployment record including per-task-group health counts,
        used to monitor a job roll-out to completion.
        """
        response = await self._transport.request("GET", f"/deployment/{deployment_id}")
        return self._decode(response, Deployment)
