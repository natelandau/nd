"""Allocations resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.allocation import AllocListStub
from nd.nomad.resources.base import BaseResource


class AllocationsResource(BaseResource):
    """Read and lifecycle access to Nomad allocations."""

    async def list(self) -> builtins.list[AllocListStub]:
        """List all allocations (``GET /v1/allocations``), following pagination."""
        return await self._paginate_list(path="/allocations", item_type=AllocListStub)

    async def signal(self, alloc_id: str, *, signal: str, task: str) -> None:
        """Send a signal to one task in an allocation.

        ``POST /v1/client/allocation/:alloc_id/signal``. Use to trigger an out-of-band
        action in a running task, such as making a scheduled job run now. Requires the
        ``alloc-lifecycle`` ACL capability, which the read-only endpoints do not.

        Args:
            alloc_id: Allocation carrying the task.
            signal: Canonical signal name to send, such as ``SIGUSR1``.
            task: Name of the task to signal.
        """
        await self._transport.request(
            method="POST",
            path=f"/client/allocation/{alloc_id}/signal",
            json={"Signal": signal, "Task": task},
        )
