"""Jobs resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.allocation import AllocListStub
from nd.nomad.models.job import Job, JobDeregisterResponse, JobListStub
from nd.nomad.resources.base import BaseResource


class JobsResource(BaseResource):
    """Read and lifecycle access to Nomad jobs."""

    async def list(self) -> builtins.list[JobListStub]:
        """List all jobs (``GET /v1/jobs``), following pagination."""
        return await self._paginate_list("/jobs", JobListStub)

    async def read(self, job_id: str) -> Job:
        """Read a single job (``GET /v1/job/:id``)."""
        response = await self._transport.request("GET", f"/job/{job_id}")
        return self._decode(response, Job)

    async def stop(self, job_id: str, *, purge: bool = False) -> JobDeregisterResponse:
        """Stop a job (``DELETE /v1/job/:id``).

        Pass ``purge=True`` to garbage-collect the job instead of leaving it ``dead``.
        """
        response = await self._transport.request(
            "DELETE", f"/job/{job_id}", params={"purge": purge}
        )
        return self._decode(response, JobDeregisterResponse)

    async def allocations(self, job_id: str) -> builtins.list[AllocListStub]:
        """List a job's allocations (``GET /v1/job/:id/allocations``), following pagination.

        Used to watch a stopped job drain to a terminal state.
        """
        return await self._paginate_list(f"/job/{job_id}/allocations", AllocListStub)
