"""Models for the Nomad nodes endpoints."""

from __future__ import annotations

import msgspec


class NodeListStub(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """A node as returned by ``GET /v1/nodes``."""

    id: str = msgspec.field(name="ID")
    datacenter: str
    name: str
    node_class: str
    node_pool: str = "default"
    drain: bool
    scheduling_eligibility: str
    status: str
    version: str
    create_index: int
    modify_index: int


class Node(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """A node as returned by ``GET /v1/node/:id``."""

    id: str = msgspec.field(name="ID")
    datacenter: str
    name: str
    node_class: str
    node_pool: str = "default"
    status: str
    drain: bool
    scheduling_eligibility: str
    http_addr: str = msgspec.field(name="HTTPAddr")
    tls_enabled: bool = msgspec.field(name="TLSEnabled")
    attributes: dict[str, str] = msgspec.field(default_factory=dict)
    meta: dict[str, str] = msgspec.field(default_factory=dict)
    create_index: int
    modify_index: int
