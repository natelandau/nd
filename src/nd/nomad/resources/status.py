"""Status resource for the Nomad API."""

from __future__ import annotations

from nd.nomad.resources.base import BaseResource


class StatusResource(BaseResource):
    """Read access to cluster status endpoints."""

    async def leader(self) -> str:
        """Return the current leader's RPC address (``GET /v1/status/leader``)."""
        response = await self._transport.request("GET", "/status/leader")
        return self._decode(response, str)
