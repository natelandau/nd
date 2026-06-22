"""Jobs resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.job import Job, JobListStub
from nd.nomad.resources.base import BaseResource


class JobsResource(BaseResource):
    """Read access to Nomad jobs."""

    async def list(self) -> builtins.list[JobListStub]:
        """List all jobs (``GET /v1/jobs``), following pagination."""
        stubs: list[JobListStub] = []
        async for response in self._transport.paginate("/jobs"):
            stubs.extend(self._decode_list(response, JobListStub))
        return stubs

    async def read(self, job_id: str) -> Job:
        """Read a single job (``GET /v1/job/:id``)."""
        response = await self._transport.request("GET", f"/job/{job_id}")
        return self._decode(response, Job)
