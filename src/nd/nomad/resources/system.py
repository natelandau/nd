"""System resource for the Nomad API."""

from __future__ import annotations

from nd.nomad.resources.base import BaseResource


class SystemResource(BaseResource):
    """Cluster-wide housekeeping operations."""

    async def gc(self) -> None:
        """Force garbage collection of dead objects (``PUT /v1/system/gc``).

        Reclaims dead jobs, terminal allocations/evaluations, and GC-eligible
        nodes. Safe and idempotent; the response carries no body.
        """
        await self._transport.request("PUT", "/system/gc")

    async def reconcile_summaries(self) -> None:
        """Recompute drifted job summary counts (``PUT /v1/system/reconcile/summaries``).

        Repairs job summaries that have diverged from actual allocation state.
        Safe and idempotent; the response carries no body.
        """
        await self._transport.request("PUT", "/system/reconcile/summaries")
