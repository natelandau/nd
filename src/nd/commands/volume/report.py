"""Pure planning and join logic for ``nd volume`` (no I/O, no Rich)."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nd.nodes import node_label

if TYPE_CHECKING:
    from nd.nomad.models.node import Node
    from nd.nomad.models.volume import HostVolumeListStub
    from nd.volumefiles import VolumeSpec

# Node Meta key holding the per-node storage root that host paths are built under.
STORAGE_ROOT_META = "nfsStorageRoot"

# Exact reason string used when a volume is already registered on a node.
# Exported so renderers can compare against this without duplicating the literal.
ALREADY_REGISTERED_REASON = "already registered on this node"


@dataclass(frozen=True)
class Registration:
    """A planned per-node action for one host-volume spec."""

    spec: VolumeSpec
    node_id: str
    node_name: str
    host_path: str | None  # None when the node is skipped
    reason: str  # why the node is skipped; empty when registering

    @property
    def is_skipped(self) -> bool:
        """Report whether the plan leaves this node alone instead of registering on it."""
        return self.host_path is None


class OutcomeKind(enum.Enum):
    """How an attempted volume action on one node ended."""

    DONE = enum.auto()
    DRY_RUN = enum.auto()
    FAILED = enum.auto()


@dataclass(frozen=True)
class Outcome:
    """The result of one volume register or delete call, with the error when it failed."""

    kind: OutcomeKind
    error: str = ""


DONE = Outcome(kind=OutcomeKind.DONE)
DRY_RUN = Outcome(kind=OutcomeKind.DRY_RUN)


@dataclass(frozen=True)
class VolumeRow:
    """One rendered row: a spec and the nodes it is registered on."""

    name: str
    nodes: list[str]
    registered: bool


def build_register_payload(spec: VolumeSpec, node_id: str, host_path: str) -> dict:
    """Build the JSON ``Volume`` body for ``PUT /v1/volume/host/register``.

    Capabilities are pascal-cased into the ``RequestedCapabilities`` shape the register
    endpoint expects.
    """
    return {
        "Name": spec.name,
        "Type": "host",
        "NodeID": node_id,
        "HostPath": host_path,
        "RequestedCapabilities": [
            {"AccessMode": c.get("access_mode"), "AttachmentMode": c.get("attachment_mode")}
            for c in spec.capabilities
        ],
    }


def plan_registrations(
    specs: list[VolumeSpec], nodes: list[Node], registered: list[HostVolumeListStub]
) -> list[Registration]:
    """Plan a register-or-skip action for each spec on each ready node.

    Only ready nodes are considered. A node is skipped when it lacks the
    ``nfsStorageRoot`` meta, when the spec has no ``relative_path``, or when the volume
    is already registered on it. Host paths are ``<nfsStorageRoot>/<relative_path>``.
    """
    already = {(v.name, v.node_id) for v in registered}
    plan: list[Registration] = []
    ready = [n for n in nodes if n.status == "ready"]
    for spec in specs:
        for node in ready:
            if (spec.name, node.id) in already:
                plan.append(_skip(spec, node, ALREADY_REGISTERED_REASON))
                continue
            if not spec.relative_path:
                plan.append(_skip(spec, node, "spec has no relative_path"))
                continue
            storage_root = node.meta.get(STORAGE_ROOT_META)
            if not storage_root:
                plan.append(_skip(spec, node, f"node has no {STORAGE_ROOT_META} meta"))
                continue
            host_path = f"{storage_root.rstrip('/')}/{spec.relative_path}"
            plan.append(
                Registration(
                    spec=spec,
                    node_id=node.id,
                    node_name=node.name,
                    host_path=host_path,
                    reason="",
                )
            )
    return plan


def _skip(spec: VolumeSpec, node: Node, reason: str) -> Registration:
    """Build a skip Registration for ``spec`` on ``node``."""
    return Registration(
        spec=spec,
        node_id=node.id,
        node_name=node.name,
        host_path=None,
        reason=reason,
    )


def plan_deletions(
    specs: list[VolumeSpec], registered: list[HostVolumeListStub]
) -> list[HostVolumeListStub]:
    """Select registered host volumes whose name matches one of the discovered specs."""
    names = {s.name for s in specs}
    return [v for v in registered if v.name in names]


def volume_node_labels(
    registered: list[HostVolumeListStub], node_names: dict[str, str]
) -> dict[str, list[str]]:
    """Map each registered volume name to the sorted names of the nodes it is on.

    Use it wherever output lists volumes by where they live, so every view resolves
    node IDs to the same readable names.

    Args:
        registered: Host volume registrations, one per volume per node.
        node_names: Node names keyed by node ID; unknown IDs fall back to a short ID.

    Returns:
        dict[str, list[str]]: Sorted node labels keyed by volume name.
    """
    labels: dict[str, list[str]] = {}
    for vol in registered:
        labels.setdefault(vol.name, []).append(
            node_label(node_names=node_names, node_id=vol.node_id)
        )
    return {name: sorted(nodes) for name, nodes in labels.items()}


def build_list_rows(
    specs: list[VolumeSpec],
    registered: list[HostVolumeListStub],
    node_names: dict[str, str],
) -> list[VolumeRow]:
    """Join specs to their registrations, one row per spec, sorted by name.

    Node IDs resolve to display names through ``node_names``, so the table shows
    hostnames rather than GUIDs.
    """
    labels = volume_node_labels(registered=registered, node_names=node_names)
    rows = [
        VolumeRow(
            name=spec.name,
            nodes=labels.get(spec.name, []),
            registered=spec.name in labels,
        )
        for spec in specs
    ]
    return sorted(rows, key=lambda r: r.name)
