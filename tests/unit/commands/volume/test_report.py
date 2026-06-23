"""Tests for volume command planning logic."""

from pathlib import Path

from nd.commands.volume.report import (
    build_list_rows,
    build_register_payload,
    plan_deletions,
    plan_registrations,
)
from nd.nomad.models.node import Node
from nd.nomad.models.volume import HostVolumeListStub
from nd.volumefiles import VolumeSpec

_CAPS = [{"access_mode": "single-node-writer", "attachment_mode": "file-system"}]


def _spec(name="data", relative="data") -> VolumeSpec:
    return VolumeSpec(
        path=Path(f"/v/{name}.hcl"), name=name, capabilities=_CAPS, relative_path=relative
    )


def _node(*, node_id="n1", name="node1", status="ready", root="/srv") -> Node:
    return Node(
        id=node_id,
        datacenter="dc1",
        name=name,
        node_class="",
        node_pool="default",
        status=status,
        drain=False,
        scheduling_eligibility="eligible",
        http_addr="10.0.0.1:4646",
        tls_enabled=False,
        meta={"nfsStorageRoot": root} if root else {},
        create_index=1,
        modify_index=2,
    )


def _registered(*, name="data", node_id="n1", vol_id="data:n1") -> HostVolumeListStub:
    return HostVolumeListStub(id=vol_id, name=name, node_id=node_id)


def test_build_register_payload_maps_capabilities_to_pascal() -> None:
    """Verify the register payload carries host fields and pascal-cased capabilities."""
    # Given a spec, node id, and host path
    # When building the payload
    payload = build_register_payload(_spec(), "n1", "/srv/data")
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
    plan = plan_registrations([_spec()], [_node(root="/srv/")], [])
    # When planning registrations
    # Then a single register action is planned with the joined host path
    assert len(plan) == 1
    assert plan[0].action == "register"
    assert plan[0].host_path == "/srv/data"


def test_plan_registrations_skips_node_without_meta() -> None:
    """Verify a node missing nfsStorageRoot meta is skipped with a reason."""
    # Given a ready node without the storage-root meta
    plan = plan_registrations([_spec()], [_node(root="")], [])
    # When planning registrations
    # Then the node is skipped
    assert plan[0].action == "skip"
    assert "nfsStorageRoot" in plan[0].reason


def test_plan_registrations_skips_already_registered() -> None:
    """Verify an already-registered name+node pair is skipped."""
    # Given a node where the volume is already registered
    plan = plan_registrations([_spec()], [_node()], [_registered()])
    # When planning registrations
    # Then it is skipped as already registered
    assert plan[0].action == "skip"
    assert "already" in plan[0].reason.lower()


def test_plan_registrations_ignores_down_nodes() -> None:
    """Verify non-ready nodes produce no registration entries."""
    # Given a down node
    plan = plan_registrations([_spec()], [_node(status="down")], [])
    # When planning registrations
    # Then nothing is planned for it
    assert plan == []


def test_plan_registrations_skips_spec_without_relative_path() -> None:
    """Verify a spec lacking relative_path is skipped with a reason."""
    # Given a spec with no relative_path
    plan = plan_registrations([_spec(relative=None)], [_node()], [])
    # When planning registrations
    # Then it is skipped
    assert plan[0].action == "skip"
    assert "relative_path" in plan[0].reason


def test_plan_deletions_matches_spec_names() -> None:
    """Verify deletions select registered volumes whose name matches a spec."""
    # Given two registered volumes, one matching a spec name
    registered = [
        _registered(name="data", vol_id="data:n1"),
        _registered(name="other", vol_id="o:n1"),
    ]
    # When planning deletions for the "data" spec
    to_delete = plan_deletions([_spec(name="data")], registered)
    # Then only the matching registration is selected
    assert [v.id for v in to_delete] == ["data:n1"]


def test_build_list_rows_joins_specs_to_registrations() -> None:
    """Verify list rows show the node names each spec is registered on."""
    # Given a spec registered on one node and another spec registered nowhere
    registered = [_registered(name="data", node_id="n1")]
    node_names = {"n1": "node-alpha"}
    # When building list rows
    rows = build_list_rows([_spec(name="data"), _spec(name="empty")], registered, node_names)
    # Then the rows reflect registration state with resolved node names, sorted by name
    by_name = {r.name: r for r in rows}
    assert by_name["data"].registered is True
    assert by_name["data"].nodes == ["node-alpha"]
    assert by_name["empty"].registered is False


def test_build_list_rows_aggregates_nodes_by_volume() -> None:
    """Verify a volume registered on two nodes yields one row with both node names sorted."""
    # Given a single volume registered on two different nodes
    registered = [
        _registered(name="data", node_id="n1"),
        _registered(name="data", node_id="n2"),
    ]
    node_names = {"n1": "alpha", "n2": "beta"}
    # When building list rows for one spec
    rows = build_list_rows([_spec(name="data")], registered, node_names)
    # Then one row is returned with both names sorted alphabetically
    assert len(rows) == 1
    assert rows[0].nodes == ["alpha", "beta"]


def test_build_list_rows_fallback_on_unknown_node_id() -> None:
    """Verify an unknown node id falls back to the first 8 chars of the id."""
    # Given a registration whose node_id has no entry in the name map
    registered = [_registered(name="data", node_id="abcdef1234567890")]
    node_names: dict[str, str] = {}
    # When building list rows with an empty name map
    rows = build_list_rows([_spec(name="data")], registered, node_names)
    # Then the node is represented by the first 8 chars of its id
    assert rows[0].nodes == ["abcdef12"]
