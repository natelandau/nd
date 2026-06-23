"""Tests for volume command rendering."""

from pathlib import Path

import pytest
from nclutils import pp
from rich.console import Console

from nd.commands.volume.render import (
    render_deletion_results,
    render_list,
    render_registration_results,
)
from nd.commands.volume.report import ALREADY_REGISTERED_REASON, Registration, VolumeRow
from nd.nomad.models.volume import HostVolumeListStub
from nd.volumefiles import VolumeSpec


@pytest.fixture(autouse=True)
def _restore_pp() -> None:  # type: ignore[return]
    """Restore the global pp emitter after each test."""
    original = pp.get_default()
    yield
    pp.set_default(original)


def _record() -> Console:
    """Build a recording console wired into pp for output capture."""
    console = Console(theme=pp.THEME, record=True, force_terminal=True, width=100)
    emitter = pp.Emitter(console=console, err_console=console)
    pp.set_default(emitter)
    return console


def _spec(name: str = "data") -> VolumeSpec:
    return VolumeSpec(
        path=Path(f"/v/{name}.hcl"),
        name=name,
        capabilities=[{"access_mode": "x", "attachment_mode": "file-system"}],
        relative_path="data",
    )


def _reg(
    *,
    spec_name: str = "data",
    node_name: str = "node1",
    action: str = "register",
    reason: str = "",
    host_path: str | None = "/srv/data",
) -> Registration:
    return Registration(
        spec=_spec(spec_name),
        node_id="n1",
        node_name=node_name,
        host_path=host_path,
        action=action,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# render_list tests
# ---------------------------------------------------------------------------


def test_render_list_shows_registered_nodes() -> None:
    """Verify the list table shows a registered volume's node names, not raw IDs."""
    # Given a recording console and one registered, one unregistered row
    console = _record()
    rows = [
        VolumeRow(name="data", nodes=["node-alpha"], registered=True),
        VolumeRow(name="cache", nodes=[], registered=False),
    ]
    # When rendering
    render_list(rows)
    out = console.export_text()
    # Then both volumes appear and the name (not a raw GUID) is shown
    assert "data" in out
    assert "node-alpha" in out
    assert "cache" in out


def test_render_list_shows_comma_separated_node_names_for_multi_node_volume() -> None:
    """Verify a volume on multiple nodes shows comma-separated names in one row."""
    # Given a volume registered on two nodes
    console = _record()
    rows = [VolumeRow(name="data", nodes=["alpha", "beta"], registered=True)]
    # When rendering
    render_list(rows)
    out = console.export_text()
    # Then both node names appear together in the output
    assert "alpha" in out
    assert "beta" in out


def test_render_list_empty_hints_config() -> None:
    """Verify an empty list nudges the user to set [volumes] directories."""
    # Given a recording console wired to both stdout and stderr paths
    console = _record()
    # When rendering an empty list
    render_list([])
    # Then the config hint is captured by the recording console
    assert "volumes" in console.export_text()


# ---------------------------------------------------------------------------
# render_registration_results tests
# ---------------------------------------------------------------------------


def test_render_registration_results_ok_leaf_shows_volume_and_node() -> None:
    """Verify a successful registration shows the volume name as tree root and node in the leaf."""
    # Given a recording console and one successful registration result
    console = _record()
    reg = _reg(spec_name="data", node_name="node1", host_path="/srv/data")
    # When rendering with outcome "ok"
    render_registration_results([(reg, "ok")])
    out = console.export_text()
    # Then the volume name appears as the tree root and the node name in the leaf
    assert "data" in out
    assert "node1" in out
    assert "registered on" in out


def test_render_registration_results_failed_leaf_shows_error() -> None:
    """Verify a failed registration shows the error text in the leaf."""
    # Given a recording console and one failed registration
    console = _record()
    reg = _reg(spec_name="data", node_name="node1")
    # When rendering with an error outcome
    render_registration_results([(reg, "connection refused")])
    out = console.export_text()
    # Then the failure is visible
    assert "data" in out
    assert "failed on" in out
    assert "connection refused" in out


def test_render_registration_results_already_registered_renders_dimly() -> None:
    """Verify an already-registered skip renders with a distinct already-registered message."""
    # Given a recording console and an already-registered skip
    console = _record()
    reg = _reg(
        spec_name="data",
        node_name="node1",
        action="skip",
        reason=ALREADY_REGISTERED_REASON,
        host_path=None,
    )
    # When rendering
    render_registration_results([(reg, "skip")])
    out = console.export_text()
    # Then the already-registered leaf text is present (not generic skip text)
    assert "already registered on" in out
    assert "node1" in out


def test_render_registration_results_generic_skip_shows_reason() -> None:
    """Verify a generic skip renders with the skip reason in the leaf."""
    # Given a recording console and a generic skip (missing relative_path)
    console = _record()
    reg = _reg(
        spec_name="data",
        node_name="node1",
        action="skip",
        reason="spec has no relative_path",
        host_path=None,
    )
    # When rendering
    render_registration_results([(reg, "skip")])
    out = console.export_text()
    # Then the reason appears in the output with skipped phrasing
    assert "skipped on" in out
    assert "relative_path" in out


def test_render_registration_results_dryrun_shows_would_register() -> None:
    """Verify a dry-run result renders with 'would register' leaf text."""
    # Given a recording console and a dry-run registration
    console = _record()
    reg = _reg(spec_name="data", node_name="node1", host_path="/srv/data")
    # When rendering with a "dryrun" outcome
    render_registration_results([(reg, "dryrun")])
    out = console.export_text()
    # Then the would-register text appears
    assert "would register on" in out
    assert "node1" in out


def test_render_registration_results_groups_by_volume() -> None:
    """Verify multiple volumes each get their own tree root in the output."""
    # Given registrations for two different volumes
    console = _record()
    results = [
        (_reg(spec_name="alpha", node_name="n1"), "ok"),
        (_reg(spec_name="beta", node_name="n2"), "ok"),
    ]
    # When rendering
    render_registration_results(results)
    out = console.export_text()
    # Then both volume names appear as separate roots
    assert "alpha" in out
    assert "beta" in out
    assert "n1" in out
    assert "n2" in out


# ---------------------------------------------------------------------------
# render_deletion_results tests
# ---------------------------------------------------------------------------


def test_render_deletion_results_deleted_shows_node_name() -> None:
    """Verify a deleted volume shows the node NAME (not the GUID) in the leaf."""
    # Given a recording console, a deleted volume, and a node_names map
    console = _record()
    vol = HostVolumeListStub(id="vol-1", name="data", node_id="n1")
    node_names = {"n1": "my-node"}
    # When rendering with outcome "deleted"
    render_deletion_results([(vol, "deleted")], node_names=node_names)
    out = console.export_text()
    # Then the node NAME appears, not the GUID
    assert "data" in out
    assert "my-node" in out
    assert "deleted on" in out
    assert "n1" not in out


def test_render_deletion_results_dryrun_shows_would_delete() -> None:
    """Verify a dry-run deletion shows 'would delete' text with the node name."""
    # Given a recording console and a would-delete result
    console = _record()
    vol = HostVolumeListStub(id="vol-2", name="cache", node_id="n2")
    node_names = {"n2": "node-beta"}
    # When rendering with outcome "would-delete"
    render_deletion_results([(vol, "would-delete")], node_names=node_names)
    out = console.export_text()
    # Then would-delete text with node name appears
    assert "cache" in out
    assert "would delete on" in out
    assert "node-beta" in out


def test_render_deletion_results_failed_shows_error() -> None:
    """Verify a failed deletion shows the error text in the leaf."""
    # Given a recording console and a failed deletion
    console = _record()
    vol = HostVolumeListStub(id="vol-3", name="data", node_id="n3")
    node_names = {"n3": "node-gamma"}
    # When rendering with an error outcome
    render_deletion_results([(vol, "some error occurred")], node_names=node_names)
    out = console.export_text()
    # Then the failure message appears
    assert "data" in out
    assert "failed on" in out
    assert "some error occurred" in out


def test_render_deletion_results_fallback_to_id_prefix_on_unknown_node() -> None:
    """Verify an unknown node_id falls back to the first 8 chars of the ID."""
    # Given a node_id not present in node_names
    console = _record()
    vol = HostVolumeListStub(id="vol-4", name="data", node_id="abcdef1234567890")
    node_names: dict[str, str] = {}
    # When rendering
    render_deletion_results([(vol, "deleted")], node_names=node_names)
    out = console.export_text()
    # Then the first 8 chars of the node_id appear as fallback
    assert "abcdef12" in out
