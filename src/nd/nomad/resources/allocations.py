"""Allocations resource for the Nomad API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import builtins
    from collections.abc import AsyncIterator
    from contextlib import AbstractAsyncContextManager

from nd.constants import LOGS_TAIL_BYTES_PER_LINE, LOGS_TAIL_MIN_BYTES
from nd.nomad.models.allocation import AllocListStub
from nd.nomad.resources.base import BaseResource

_LOG_LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")


def split_log_lines(text: str, *, keepends: bool = False) -> list[str]:
    """Split log text into lines at newlines only, as a followed log is split.

    Use it instead of ``str.splitlines``, which also splits at carriage returns, form feeds,
    and Unicode separators, so a progress bar that redraws in place would count as many
    lines.

    Args:
        text: The log text.
        keepends: Keep each line's newline, and a carriage return before it.

    Returns:
        list[str]: The lines, the last one possibly without a newline.
    """
    lines = _LOG_LINE.findall(text)
    if keepends:
        return lines
    return [line.removesuffix("\n").removesuffix("\r") for line in lines]


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

    async def _read_log_bytes(
        self,
        alloc_id: str,
        *,
        task: str,
        stream: Literal["stdout", "stderr"],
        origin: Literal["start", "end"],
        offset: int,
    ) -> bytes:
        response = await self._transport.request(
            method="GET",
            path=f"/client/fs/logs/{alloc_id}",
            params={
                "task": task,
                "type": stream,
                "origin": origin,
                "offset": offset,
                "plain": "true",
                "follow": "false",
            },
        )
        return response.content

    async def tail_log(
        self,
        alloc_id: str,
        *,
        task: str,
        stream: Literal["stdout", "stderr"],
        lines: int,
        keepends: bool = False,
    ) -> builtins.list[str]:
        """Read the last lines of one task's log without following it.

        ``GET /v1/client/fs/logs/:alloc_id`` with ``origin=end``. Use it to show recent
        output, such as why a task failed, without streaming the whole log. Nomad reads a
        log by bytes, so the read starts at an estimate for ``lines`` lines and doubles
        while the log is longer than the read and still short of lines. A first line that
        the read cut in half is dropped, unless it is the only line.

        Args:
            alloc_id: Allocation carrying the task.
            task: Name of the task whose log to read.
            stream: Which log to read.
            lines: How many lines to return at most.
            keepends: Keep each line's original line ending, as an export of the log needs.

        Returns:
            list[str]: Up to ``lines`` of the log's last lines, decoded as UTF-8 with
            undecodable bytes replaced.
        """
        max_bytes = max(LOGS_TAIL_MIN_BYTES, lines * LOGS_TAIL_BYTES_PER_LINE)
        while True:
            content = await self._read_log_bytes(
                alloc_id, task=task, stream=stream, origin="end", offset=max_bytes
            )
            truncated = len(content) >= max_bytes
            found = split_log_lines(content.decode(errors="replace"), keepends=keepends)
            if truncated and len(found) > 1:
                found = found[1:]
            if len(found) >= lines or not truncated:
                return found[-lines:]
            max_bytes *= 2

    async def read_log(
        self, alloc_id: str, *, task: str, stream: Literal["stdout", "stderr"]
    ) -> bytes:
        """Read one task's whole log without following it.

        ``GET /v1/client/fs/logs/:alloc_id`` from the start of the log. Use it to export
        a complete log.

        Args:
            alloc_id: Allocation carrying the task.
            task: Name of the task whose log to read.
            stream: Which log to read.

        Returns:
            bytes: The raw log.
        """
        return await self._read_log_bytes(
            alloc_id, task=task, stream=stream, origin="start", offset=0
        )

    def follow_logs(
        self,
        alloc_id: str,
        *,
        task: str,
        stream: Literal["stdout", "stderr"],
        origin: Literal["start", "end"],
        offset: int,
    ) -> AbstractAsyncContextManager[AsyncIterator[bytes]]:
        """Open a followed log of one task, yielding its raw bytes as the task writes them.

        ``GET /v1/client/fs/logs/:alloc_id`` with ``follow=true``. Use it to tail a live
        task. Entering the context means Nomad accepted the request, even before any output
        arrives; leaving it closes the stream. Nomad keeps the stream open after the task
        stops, until the allocation's files are garbage collected, so a caller must decide
        for itself when to stop. Chunks are not aligned to line or character boundaries.

        Args:
            alloc_id: Allocation carrying the task.
            task: Name of the task whose log to follow.
            stream: Which log to follow.
            origin: Whether ``offset`` counts from the start or the end of the log.
            offset: How many bytes from ``origin`` to start at.

        Returns:
            AbstractAsyncContextManager[AsyncIterator[bytes]]: Yields the chunk iterator.
        """
        return self._transport.stream(
            "GET",
            f"/client/fs/logs/{alloc_id}",
            params={
                "task": task,
                "type": stream,
                "origin": origin,
                "offset": offset,
                "follow": "true",
                "plain": "true",
            },
        )
