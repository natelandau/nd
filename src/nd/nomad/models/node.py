"""Models for the Nomad nodes endpoints."""

from __future__ import annotations

import msgspec

from nd.nomad.models import NomadModel


class _NodeCommon(NomadModel, frozen=True, kw_only=True):
    """Fields shared by the node list stub and the full node record."""

    id: str = msgspec.field(name="ID")
    datacenter: str
    name: str
    node_class: str
    node_pool: str = "default"
    status: str
    drain: bool
    scheduling_eligibility: str
    create_index: int
    modify_index: int

    @property
    def is_eligible(self) -> bool:
        """Whether the scheduler may place new work on this node.

        A draining node reads as ineligible even before Nomad flips its eligibility flag.
        """
        return self.scheduling_eligibility == "eligible" and not self.drain


class NodeListStub(_NodeCommon, frozen=True, kw_only=True):
    """A node as returned by ``GET /v1/nodes``."""

    address: str = ""
    version: str


class Node(_NodeCommon, frozen=True, kw_only=True):
    """A node as returned by ``GET /v1/node/:id``."""

    meta: dict[str, str] = msgspec.field(default_factory=dict)
