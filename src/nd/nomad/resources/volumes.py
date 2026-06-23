"""Volumes resource for the Nomad API (dynamic host volumes)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.volume import HostVolumeListStub, HostVolumeRegisterResponse
from nd.nomad.resources.base import BaseResource


class VolumesResource(BaseResource):
    """Read and lifecycle access to Nomad dynamic host volumes."""

    async def list(self) -> builtins.list[HostVolumeListStub]:
        """List dynamic host volumes (``GET /v1/volumes?type=host``).

        A direct request rather than the pagination helper: host-volume counts are
        small, and this keeps the ``type=host`` query param on the request.
        """
        response = await self._transport.request("GET", "/volumes", params={"type": "host"})
        return self._decode_list(response, HostVolumeListStub)

    async def register(self, volume: dict) -> HostVolumeRegisterResponse:
        """Register an existing host volume (``PUT /v1/volume/host/register``).

        ``volume`` is the JSON ``Volume`` body (Name/Type/NodeID/HostPath/...); it is
        wrapped under a ``Volume`` key as the endpoint expects.
        """
        response = await self._transport.request(
            "PUT", "/volume/host/register", json={"Volume": volume}
        )
        return self._decode(response, HostVolumeRegisterResponse)

    async def delete(self, volume_id: str) -> None:
        """Delete a host volume by id (``DELETE /v1/volume/host/:id/delete``).

        Only removes Nomad's record; the underlying mount data is untouched.
        """
        await self._transport.request("DELETE", f"/volume/host/{volume_id}/delete")
