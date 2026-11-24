"""Volumes resource for the Nomad API (dynamic host volumes)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.volume import HostVolumeListStub
from nd.nomad.resources.base import BaseResource


class VolumesResource(BaseResource):
    """Read and lifecycle access to Nomad dynamic host volumes."""

    async def list(self) -> builtins.list[HostVolumeListStub]:
        """List dynamic host volumes (``GET /v1/volumes?type=host``), following pagination."""
        return await self._paginate_list(
            path="/volumes", item_type=HostVolumeListStub, params={"type": "host"}
        )

    async def register(self, volume: dict) -> None:
        """Register an existing host volume (``PUT /v1/volume/host/register``).

        ``volume`` is the JSON ``Volume`` body (Name/Type/NodeID/HostPath/...); it is
        wrapped under a ``Volume`` key as the endpoint expects.
        """
        await self._transport.request(
            method="PUT", path="/volume/host/register", json={"Volume": volume}
        )

    async def delete(self, volume_id: str) -> None:
        """Delete a host volume by id (``DELETE /v1/volume/host/:id/delete``).

        Only removes Nomad's record; the underlying mount data is untouched.
        """
        await self._transport.request(method="DELETE", path=f"/volume/host/{volume_id}/delete")
