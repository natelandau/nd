"""Agent resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nd.nomad.models.agent import AgentMembers
from nd.nomad.resources.base import BaseResource

if TYPE_CHECKING:
    from nd.nomad.models.agent import AgentMember


class AgentResource(BaseResource):
    """Read access to the local Nomad agent."""

    async def members(self) -> list[AgentMember]:
        """List the cluster's server members (``GET /v1/agent/members``)."""
        response = await self._transport.request(method="GET", path="/agent/members")
        return self._decode(response=response, type_=AgentMembers).members
