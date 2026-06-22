"""Models for the Nomad jobs endpoints."""

from __future__ import annotations

import msgspec


class JobListStub(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """A job as returned by ``GET /v1/jobs``."""

    id: str = msgspec.field(name="ID")
    name: str
    type: str = msgspec.field(name="Type")
    status: str
    priority: int
    namespace: str = "default"
    create_index: int
    modify_index: int


class Job(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """A job as returned by ``GET /v1/job/:id``."""

    id: str = msgspec.field(name="ID")
    name: str
    type: str = msgspec.field(name="Type")
    status: str
    priority: int
    namespace: str = "default"
    datacenters: list[str] = msgspec.field(default_factory=list)
    create_index: int
    modify_index: int
