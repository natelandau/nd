"""Tests for volume command planning logic."""

from pathlib import Path

import pytest

from nd.commands.volume.report import (
    build_list_rows,
    build_register_payload,
    plan_deletions,
    plan_registrations,
)
from nd.nomad.models.node import Node
from nd.nomad.models.volume import HostVolumeListStub
from nd.volumefiles import VolumeSpec
from tests.builders import host_volume_stub, node_detail


def _spec(name: str = "data", *, relative: str | None = "data") -> VolumeSpec:
    """Build a host volume spec with one single-node-writer capability.

    Returns:
        VolumeSpec: The spec.
    """
    return VolumeSpec(
        path=Path(f"/v/{name}.hcl"),
        name=name,
        capabilities=[{"access_mode": "single-node-writer", "attachment_mode": "file-system"}],
        relative_path=relative,
    )


def _storage_node(root: str = "/srv", *, status: str = "ready") -> Node:
    """Build a node whose meta carries the storage root, or no meta when `root` is empty.

    Returns:
        Node: The node.
    """
    return node_detail(status=status, meta={"nfsStorageRoot": root} if root else {})


def test_build_register_payload_maps_capabilities_to_pascal() -> None:
    """Verify the register payload carries host fields and pascal-cased capabilities."""
    # Given a spec, node id, and host path
    # When building the payload
    payload = build_register_payload(spec=_spec(), node_id="n1", host_path="/srv/data")

    # Then it has the host-volume register fields
    assert payload["Name"] == "data"
    assert payload["Type"] == "host"
    assert payload["NodeID"] == "n1"
    assert payload["HostPath"] == "/srv/data"
    assert payload["RequestedCapabilities"] == [
        {"AccessMode": "single-node-writer", "AttachmentMode": "file-system"}
    ]


def test_plan_registrations_builds_host_path_from_meta() -> None:
    """Verify a ready node with storage-root meta yields a register action."""
    # Given one host spec and one ready node with nfsStorageRoot meta
    # When planning registrations
    plan = plan_registrations(specs=[_spec()], nodes=[_storage_node("/srv/")], registered=[])

    # Then a single register action is planned with the joined host path
    assert len(plan) == 1
    assert plan[0].is_skipped is False
    assert plan[0].host_path == "/srv/data"


@pytest.mark.parametrize(
    ("spec", "node", "registered", "reason_fragment"),
    [
        pytest.param(_spec(), _storage_node(""), [], "nfsStorageRoot", id="node-without-meta"),
        pytest.param(
            _spec(), _storage_node(), [host_volume_stub("data")], "already", id="already-registered"
        ),
        pytest.param(
            _spec(relative=None), _storage_node(), [], "relative_path", id="no-relative-path"
        ),
    ],
)
def test_plan_registrations_skips_with_reason(
    spec: VolumeSpec, node: Node, registered: list[HostVolumeListStub], reason_fragment: str
) -> None:
    """Verify a node is skipped, with a reason, when it cannot or need not take the volume."""
    # When planning registrations
    plan = plan_registrations(specs=[spec], nodes=[node], registered=registered)

    # Then the node is skipped and the reason names the cause
    assert plan[0].is_skipped is True
    assert reason_fragment in plan[0].reason


def test_plan_registrations_ignores_down_nodes() -> None:
    """Verify non-ready nodes produce no registration entries."""
    # Given a down node
    # When planning registrations
    plan = plan_registrations(specs=[_spec()], nodes=[_storage_node(status="down")], registered=[])

    # Then nothing is planned for it
    assert plan == []


def test_plan_deletions_matches_spec_names() -> None:
    """Verify deletions select registered volumes whose name matches a spec."""
    # Given two registered volumes, one matching a spec name
    registered = [host_volume_stub("data"), host_volume_stub("other")]

    # When planning deletions for the "data" spec
    to_delete = plan_deletions(specs=[_spec(name="data")], registered=registered)

    # Then only the matching registration is selected
    assert [v.id for v in to_delete] == ["data:n1"]


def test_build_list_rows_joins_specs_to_registrations() -> None:
    """Verify list rows show the node names each spec is registered on."""
    # Given a spec registered on one node and another spec registered nowhere
    registered = [host_volume_stub("data")]

    # When building list rows
    rows = build_list_rows(
        specs=[_spec(name="data"), _spec(name="empty")],
        registered=registered,
        node_names={"n1": "node-alpha"},
    )

    # Then the rows reflect registration state with resolved node names
    by_name = {r.name: r for r in rows}
    assert by_name["data"].registered is True
    assert by_name["data"].nodes == ["node-alpha"]
    assert by_name["empty"].registered is False


def test_build_list_rows_aggregates_nodes_by_volume() -> None:
    """Verify a volume registered on two nodes yields one row with both node names sorted."""
    # Given a single volume registered on two different nodes
    registered = [host_volume_stub("data", node_id="n1"), host_volume_stub("data", node_id="n2")]

    # When building list rows for one spec
    rows = build_list_rows(
        specs=[_spec(name="data")], registered=registered, node_names={"n1": "alpha", "n2": "beta"}
    )

    # Then one row is returned with both names sorted alphabetically
    assert len(rows) == 1
    assert rows[0].nodes == ["alpha", "beta"]


def test_build_list_rows_fallback_on_unknown_node_id() -> None:
    """Verify an unknown node id falls back to the first 8 chars of the id."""
    # Given a registration whose node_id has no entry in the name map
    registered = [host_volume_stub("data", node_id="abcdef1234567890")]

    # When building list rows with an empty name map
    rows = build_list_rows(specs=[_spec(name="data")], registered=registered, node_names={})

    # Then the node is represented by the first 8 chars of its id
    assert rows[0].nodes == ["abcdef12"]
