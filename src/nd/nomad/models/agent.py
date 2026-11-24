"""Models for the Nomad agent endpoints."""

from __future__ import annotations

import msgspec

from nd.nomad.models import NomadModel


class AgentMember(NomadModel, frozen=True, kw_only=True):
    """A single serf member entry from the agent's view of the cluster."""

    name: str
    addr: str
    status: str
    tags: dict[str, str] = msgspec.field(default_factory=dict)


class AgentMembers(NomadModel, frozen=True, kw_only=True):
    """Server membership as returned by ``GET /v1/agent/members``."""

    members: list[AgentMember] = msgspec.field(default_factory=list)
