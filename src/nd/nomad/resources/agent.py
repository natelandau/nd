"""Agent resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nd.nomad.models.agent import AgentMembers, AgentSelf
from nd.nomad.resources.base import BaseResource

if TYPE_CHECKING:
    from nd.nomad.models.agent import AgentMember


class AgentResource(BaseResource):
    """Read access to the local Nomad agent."""

    async def self(self) -> AgentSelf:
        """Return the agent's view of itself (``GET /v1/agent/self``)."""
        response = await self._transport.request("GET", "/agent/self")
        return self._decode(response, AgentSelf)

    async def members(self) -> list[AgentMember]:
        """List the cluster's server members (``GET /v1/agent/members``)."""
        response = await self._transport.request("GET", "/agent/members")
        return list(self._decode(response, AgentMembers).members)
