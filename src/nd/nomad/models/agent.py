"""Models for the Nomad agent endpoints."""

from __future__ import annotations

import msgspec


class AgentMember(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """A single serf member entry from the agent's view of the cluster."""

    name: str
    addr: str
    status: str
    tags: dict[str, str] = msgspec.field(default_factory=dict)


class AgentMembers(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """Server membership as returned by ``GET /v1/agent/members``."""

    members: list[AgentMember] = msgspec.field(default_factory=list)


class AgentSelf(msgspec.Struct, frozen=True, kw_only=True):
    """Subset of ``GET /v1/agent/self`` used to confirm connectivity."""

    member: AgentMember
