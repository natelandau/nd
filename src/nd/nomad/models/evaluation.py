"""Models for the Nomad evaluations endpoints."""

from __future__ import annotations

import msgspec

from nd.nomad.models import NomadModel


class EvalListStub(NomadModel, frozen=True, kw_only=True):
    """An evaluation as returned by ``GET /v1/evaluations``."""

    id: str = msgspec.field(name="ID")
    job_id: str = msgspec.field(name="JobID")
    namespace: str = "default"
    status: str
    type: str
    triggered_by: str = ""
    queued_allocations: dict[str, int] = msgspec.field(default_factory=dict)
    create_index: int
    modify_index: int
