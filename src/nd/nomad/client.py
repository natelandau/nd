"""High-level Nomad API client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from nd.nomad.resources.agent import AgentResource
from nd.nomad.resources.allocations import AllocationsResource
from nd.nomad.resources.deployments import DeploymentsResource
from nd.nomad.resources.evaluations import EvaluationsResource
from nd.nomad.resources.jobs import JobsResource
from nd.nomad.resources.nodes import NodesResource
from nd.nomad.resources.status import StatusResource
from nd.nomad.resources.system import SystemResource
from nd.nomad.resources.volumes import VolumesResource
from nd.nomad.transport import AsyncTransport

if TYPE_CHECKING:
    from nd.nomad.config import NomadConfig


class NomadClient:
    """Async entry point exposing Nomad resource namespaces."""

    def __init__(self, config: NomadConfig) -> None:
        self._transport = AsyncTransport(config)
        self.agent = AgentResource(self._transport)
        self.nodes = NodesResource(self._transport)
        self.jobs = JobsResource(self._transport)
        self.allocations = AllocationsResource(self._transport)
        self.status = StatusResource(self._transport)
        self.deployments = DeploymentsResource(self._transport)
        self.evaluations = EvaluationsResource(self._transport)
        self.system = SystemResource(self._transport)
        self.volumes = VolumesResource(self._transport)

    async def aclose(self) -> None:
        """Close the underlying transport."""
        await self._transport.aclose()

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the async context manager and close the transport."""
        await self.aclose()
