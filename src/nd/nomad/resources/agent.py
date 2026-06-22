"""Agent resource for the Nomad API."""

from __future__ import annotations

from nd.nomad.models.agent import AgentSelf
from nd.nomad.resources.base import BaseResource


class AgentResource(BaseResource):
    """Read access to the local Nomad agent."""

    async def self(self) -> AgentSelf:
        """Return the agent's view of itself (``GET /v1/agent/self``)."""
        response = await self._transport.request("GET", "/agent/self")
        return self._decode(response, AgentSelf)
