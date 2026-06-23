"""Models for the Nomad deployments endpoints."""

from __future__ import annotations

import msgspec


class DeploymentListStub(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """A deployment as returned by ``GET /v1/deployments``."""

    id: str = msgspec.field(name="ID")
    job_id: str = msgspec.field(name="JobID")
    namespace: str = "default"
    status: str
    status_description: str = ""
    job_version: int = 0
    create_index: int
    modify_index: int
