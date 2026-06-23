"""Jobs resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

import msgspec

from nd.nomad.models.allocation import AllocListStub
from nd.nomad.models.deployment import DeploymentListStub
from nd.nomad.models.job import Job, JobDeregisterResponse, JobListStub, JobRegisterResponse
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

    async def stop(
        self, job_id: str, *, purge: bool = False, no_shutdown_delay: bool = False
    ) -> JobDeregisterResponse:
        """Stop a job (``DELETE /v1/job/:id``).

        Pass ``purge=True`` to garbage-collect the job instead of leaving it ``dead``.
        Pass ``no_shutdown_delay=True`` to bypass the configured group/task shutdown
        delays for an immediate teardown.
        """
        response = await self._transport.request(
            "DELETE",
            f"/job/{job_id}",
            params={"purge": purge, "no_shutdown_delay": no_shutdown_delay},
        )
        return self._decode(response, JobDeregisterResponse)

    async def allocations(self, job_id: str) -> builtins.list[AllocListStub]:
        """List a job's allocations (``GET /v1/job/:id/allocations``), following pagination.

        Used to watch a stopped job drain to a terminal state.
        """
        return await self._paginate_list(f"/job/{job_id}/allocations", AllocListStub)

    async def register(self, body: bytes) -> JobRegisterResponse:
        """Register a job (``POST /v1/jobs``).

        Submit the compiled ``{"Job": {...}}`` payload produced by
        ``nomad job run -output``. The bytes are decoded and sent as the JSON body
        because the transport serializes a Python object rather than raw bytes.
        """
        payload = msgspec.json.decode(body)
        response = await self._transport.request("POST", "/jobs", json=payload)
        return self._decode(response, JobRegisterResponse)

    async def deployments(self, job_id: str) -> builtins.list[DeploymentListStub]:
        """List a job's deployments (``GET /v1/job/:id/deployments``), following pagination.

        Nomad returns the most recent deployment first, used to watch a freshly
        registered service job roll out.
        """
        return await self._paginate_list(f"/job/{job_id}/deployments", DeploymentListStub)
