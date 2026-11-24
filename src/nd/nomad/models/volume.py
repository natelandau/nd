"""Models for the Nomad dynamic host-volume endpoints."""

from __future__ import annotations

import msgspec

from nd.nomad.models import NomadModel


class HostVolumeListStub(NomadModel, frozen=True, kw_only=True):
    """A dynamic host volume as returned by ``GET /v1/volumes?type=host``."""

    id: str = msgspec.field(name="ID")
    name: str
    namespace: str = "default"
    node_id: str = msgspec.field(name="NodeID", default="")
    node_pool: str = "default"
    plugin_id: str = msgspec.field(name="PluginID", default="")
    state: str = ""
