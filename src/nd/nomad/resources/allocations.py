"""Allocations resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.allocation import Allocation, AllocListStub
from nd.nomad.resources.base import BaseResource


class AllocationsResource(BaseResource):
    """Read access to Nomad allocations."""

    async def list(self) -> builtins.list[AllocListStub]:
        """List all allocations (``GET /v1/allocations``), following pagination."""
        stubs: list[AllocListStub] = []
        async for response in self._transport.paginate("/allocations"):
            stubs.extend(self._decode_list(response, AllocListStub))
        return stubs

    async def read(self, alloc_id: str) -> Allocation:
        """Read a single allocation (``GET /v1/allocation/:id``)."""
        response = await self._transport.request("GET", f"/allocation/{alloc_id}")
        return self._decode(response, Allocation)
