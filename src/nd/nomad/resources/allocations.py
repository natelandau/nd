"""Allocations resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

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

    async def restart(
        self, alloc_id: str, *, task: str | None = None, all_tasks: bool = False
    ) -> None:
        """Restart one task, or every task, in an allocation without rescheduling it.

        ``POST /v1/client/allocation/:alloc_id/restart``. Use it to bounce a hung or stale
        process in place, which is far cheaper than stopping and re-running the job.
        Requires the ``alloc-lifecycle`` ACL capability.

        Args:
            alloc_id: Allocation carrying the tasks.
            task: Name of the one task to restart, or None for the allocation's tasks.
            all_tasks: With no ``task``, also re-run tasks that already finished, such as
                non-sidecar prestart and poststart tasks. Without it Nomad restarts only
                the running tasks. Nomad rejects it combined with ``task``.
        """
        body: dict[str, str | bool] = {"AllTasks": True} if all_tasks else {}
        if task is not None:
            body["TaskName"] = task
        await self._transport.request(
            method="POST", path=f"/client/allocation/{alloc_id}/restart", json=body
        )

    async def log_tail(
        self,
        alloc_id: str,
        *,
        task: str,
        stream: Literal["stdout", "stderr"],
        max_bytes: int,
    ) -> str:
        """Read the end of one task's log without following it.

        ``GET /v1/client/fs/logs/:alloc_id`` with ``origin=end``. Use it to show why a
        task failed without streaming its whole log.

        Args:
            alloc_id: Allocation carrying the task.
            task: Name of the task whose log to read.
            stream: Which log to read.
            max_bytes: How many bytes to read back from the end of the log. The first
                line returned may be partial.

        Returns:
            str: The log text, decoded as UTF-8 with undecodable bytes replaced.
        """
        response = await self._transport.request(
            method="GET",
            path=f"/client/fs/logs/{alloc_id}",
            params={
                "task": task,
                "type": stream,
                "origin": "end",
                "offset": max_bytes,
                "plain": "true",
                "follow": "false",
            },
        )
        return response.content.decode(errors="replace")
