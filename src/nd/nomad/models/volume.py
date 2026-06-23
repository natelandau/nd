"""Models for the Nomad dynamic host-volume endpoints."""

from __future__ import annotations

import msgspec


class HostVolumeListStub(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """A dynamic host volume as returned by ``GET /v1/volumes?type=host``."""

    id: str = msgspec.field(name="ID")
    name: str
    namespace: str = "default"
    node_id: str = msgspec.field(name="NodeID", default="")
    node_pool: str = "default"
    plugin_id: str = msgspec.field(name="PluginID", default="")
    state: str = ""


class HostVolumeRegisterResponse(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """The reply from ``PUT /v1/volume/host/register``.

    Only the bits we surface are decoded; the populated volume is kept as a raw mapping
    because the response carries many computed fields we do not model.
    """

    volume: dict | None = None
    warnings: str | None = None
