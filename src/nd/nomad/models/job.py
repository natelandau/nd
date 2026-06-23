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
    submit_time: int = 0
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


class JobDeregisterResponse(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """The response from stopping a job (``DELETE /v1/job/:id``)."""

    eval_id: str = msgspec.field(name="EvalID", default="")
    eval_create_index: int = 0
    job_modify_index: int = 0


class JobRegisterResponse(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """The response from registering a job (``POST /v1/jobs``)."""

    eval_id: str = msgspec.field(name="EvalID", default="")
    eval_create_index: int = 0
    job_modify_index: int = 0
    warnings: str = ""
