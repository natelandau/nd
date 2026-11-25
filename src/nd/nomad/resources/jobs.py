"""Jobs resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import msgspec

if TYPE_CHECKING:
    import builtins

from nd.nomad.errors import NomadDecodeError
from nd.nomad.models import decode_json
from nd.nomad.models.allocation import AllocListStub
from nd.nomad.models.deployment import Deployment
from nd.nomad.models.job import (
    JobDeregisterResponse,
    JobListStub,
    JobPlanResponse,
    JobRegisterResponse,
    JobSpec,
)
from nd.nomad.resources.base import BaseResource


class JobsResource(BaseResource):
    """Read and lifecycle access to Nomad jobs."""

    async def list(self) -> builtins.list[JobListStub]:
        """List all jobs (``GET /v1/jobs``), following pagination."""
        return await self._paginate_list(path="/jobs", item_type=JobListStub)

    async def get(self, job_id: str, *, namespace: str | None = None) -> JobSpec:
        """Fetch one job's full spec (``GET /v1/job/:job_id``).

        Use this when a check needs what ``list`` leaves out, such as task images,
        resources, services, and volume requests. Pass the job's own ``namespace`` when
        it came from a listing, since a wildcard configured namespace finds no job here.
        """
        params = {"namespace": namespace} if namespace else None
        response = await self._transport.request(method="GET", path=f"/job/{job_id}", params=params)
        return self._decode(response=response, type_=JobSpec)

    async def stop(
        self, job_id: str, *, purge: bool = False, no_shutdown_delay: bool = False
    ) -> JobDeregisterResponse:
        """Stop a job (``DELETE /v1/job/:id``).

        Pass ``purge=True`` to garbage-collect the job instead of leaving it ``dead``.
        Pass ``no_shutdown_delay=True`` to bypass the configured group/task shutdown
        delays for an immediate teardown.
        """
        response = await self._transport.request(
            method="DELETE",
            path=f"/job/{job_id}",
            params={"purge": purge, "no_shutdown_delay": no_shutdown_delay},
        )
        return self._decode(response=response, type_=JobDeregisterResponse)

    async def allocations(self, job_id: str) -> builtins.list[AllocListStub]:
        """List a job's allocations (``GET /v1/job/:id/allocations``), following pagination.

        Used to watch a stopped job drain to a terminal state.
        """
        return await self._paginate_list(path=f"/job/{job_id}/allocations", item_type=AllocListStub)

    async def register(self, body: bytes) -> JobRegisterResponse:
        """Register a job (``POST /v1/jobs``).

        Submit the compiled ``{"Job": {...}}`` payload produced by
        ``nomad job run -output`` as the request body, unchanged.
        """
        response = await self._transport.request(method="POST", path="/jobs", content=body)
        return self._decode(response=response, type_=JobRegisterResponse)

    async def deployments(self, job_id: str) -> builtins.list[Deployment]:
        """List a job's deployments (``GET /v1/job/:id/deployments``), following pagination.

        The endpoint's ordering is undocumented, so callers that need the most
        recent deployment must select it by ``CreateIndex`` rather than position.
        """
        return await self._paginate_list(path=f"/job/{job_id}/deployments", item_type=Deployment)

    async def plan(self, body: bytes) -> JobPlanResponse:
        """Preview what registering a compiled job would change (``POST /v1/job/:id/plan``).

        Use this to compare a local job file with what runs, without changing the cluster.
        Pass the ``{"Job": {...}}`` payload from ``nomad job run -output``. The request
        path uses the compiled job's ID, which can differ from its name.

        Raises:
            NomadDecodeError: If ``body`` holds no job ID.
        """
        # The compiled job is untyped Nomad JSON, passed through unchanged.
        request = decode_json(data=body, type_=dict[str, object])
        job = request.get("Job")
        job_id = job.get("ID") if isinstance(job, dict) else None
        if not isinstance(job_id, str) or not job_id:
            msg = (
                f'Compiled job has no job ID; expected {{"Job": {{"ID": ...}}}}, got {body[:200]!r}'
            )
            raise NomadDecodeError(msg)
        response = await self._transport.request(
            method="POST",
            path=f"/job/{job_id}/plan",
            content=msgspec.json.encode({**request, "Diff": True}),
        )
        return self._decode(response=response, type_=JobPlanResponse)
