"""High-level Nomad API client."""

from __future__ import annotations

from typing import Self

from nd.nomad.config import NomadConfig
from nd.nomad.resources.agent import AgentResource
from nd.nomad.resources.allocations import AllocationsResource
from nd.nomad.resources.deployments import DeploymentsResource
from nd.nomad.resources.evaluations import EvaluationsResource
from nd.nomad.resources.jobs import JobsResource
from nd.nomad.resources.nodes import NodesResource
from nd.nomad.resources.status import StatusResource
from nd.nomad.transport import AsyncTransport


class NomadClient:
    """Async entry point exposing Nomad resource namespaces."""

    def __init__(self, config: NomadConfig | None = None) -> None:
        self._config = config or NomadConfig.resolve()
        self._transport = AsyncTransport(self._config)
        self.agent = AgentResource(self._transport)
        self.nodes = NodesResource(self._transport)
        self.jobs = JobsResource(self._transport)
        self.allocations = AllocationsResource(self._transport)
        self.status = StatusResource(self._transport)
        self.deployments = DeploymentsResource(self._transport)
        self.evaluations = EvaluationsResource(self._transport)

    @classmethod
    def from_config(cls, config: NomadConfig) -> NomadClient:
        """Build a client from an explicit config."""
        return cls(config=config)

    async def aclose(self) -> None:
        """Close the underlying transport."""
        await self._transport.aclose()

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the async context manager and close the transport."""
        await self.aclose()
