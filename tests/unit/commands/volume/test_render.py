"""Tests for volume command rendering."""

import pytest

from nd.commands.volume.render import (
    render_deletion_results,
    render_list,
    render_registration_results,
)
from nd.commands.volume.report import (
    ALREADY_REGISTERED_REASON,
    DONE,
    DRY_RUN,
    Outcome,
    OutcomeKind,
    Registration,
    VolumeRow,
)
from tests.builders import host_volume_stub, volume_spec
from tests.helpers import capture_output


def _registration(
    spec_name: str = "data",
    *,
    node_name: str = "node1",
    reason: str = "",
    host_path: str | None = "/srv/data",
) -> Registration:
    """Build a planned registration of one volume spec on node `n1`.

    Returns:
        Registration: The registration; skipped when `host_path` is None.
    """
    return Registration(
        spec=volume_spec(spec_name),
        node_id="n1",
        node_name=node_name,
        host_path=host_path,
        reason=reason,
    )


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        pytest.param(
            [
                VolumeRow(name="data", nodes=["node-alpha"], registered=True),
                VolumeRow(name="cache", nodes=[], registered=False),
            ],
            ["data", "node-alpha", "cache"],
            id="registered-and-unregistered",
        ),
        pytest.param(
            [VolumeRow(name="data", nodes=["alpha", "beta"], registered=True)],
            ["alpha", "beta"],
            id="multi-node-volume",
        ),
    ],
)
def test_render_list_shows_volumes_and_node_names(
    rows: list[VolumeRow], expected: list[str]
) -> None:
    """Verify the list table shows every volume and the names of the nodes it is on."""
    # Given a recording console
    console = capture_output()

    # When rendering the rows
    render_list(rows)

    # Then each volume and node name appears
    out = console.export_text()
    for fragment in expected:
        assert fragment in out


def test_render_list_empty_hints_config() -> None:
    """Verify an empty list nudges the user to set [volumes] directories."""
    # Given a recording console wired to both stdout and stderr paths
    console = capture_output()

    # When rendering an empty list
    render_list([])

    # Then the config hint is captured by the recording console
    assert "volumes" in console.export_text()


@pytest.mark.parametrize(
    ("registration", "outcome", "expected"),
    [
        pytest.param(_registration(), DONE, ["data", "node1", "registered on"], id="done"),
        pytest.param(
            _registration(),
            Outcome(kind=OutcomeKind.FAILED, error="connection refused"),
            ["data", "failed on", "connection refused"],
            id="failed",
        ),
        pytest.param(
            _registration(reason=ALREADY_REGISTERED_REASON, host_path=None),
            None,
            ["already registered on", "node1"],
            id="already-registered",
        ),
        pytest.param(
            _registration(reason="spec has no relative_path", host_path=None),
            None,
            ["skipped on", "relative_path"],
            id="skipped",
        ),
        pytest.param(_registration(), DRY_RUN, ["would register on", "node1"], id="dry-run"),
    ],
)
def test_render_registration_results_leaf_describes_outcome(
    registration: Registration, outcome: Outcome | None, expected: list[str]
) -> None:
    """Verify each registration leaf names the volume, node, and what happened there."""
    # Given a recording console
    console = capture_output()

    # When rendering one registration result
    render_registration_results([(registration, outcome)])

    # Then the leaf describes the outcome on that node
    out = console.export_text()
    for fragment in expected:
        assert fragment in out


def test_render_registration_results_groups_by_volume_under_counted_title() -> None:
    """Verify each volume gets its own tree, framed by a title counting the volumes registered."""
    # Given successful registrations across two volumes
    console = capture_output()
    results = [
        (_registration("alpha", node_name="n1"), DONE),
        (_registration("beta", node_name="n2"), DONE),
    ]

    # When rendering
    render_registration_results(results)

    # Then both volumes and nodes appear under a title with the registered count
    out = console.export_text()
    assert "alpha" in out
    assert "beta" in out
    assert "n1" in out
    assert "n2" in out
    assert "Registered 2 volumes" in out


@pytest.mark.parametrize(
    ("result", "dry_run"),
    [
        pytest.param((_registration("alpha"), DRY_RUN), False, id="dry-run-outcome"),
        pytest.param(
            (_registration("alpha", host_path=None, reason="already registered"), None),
            True,
            id="every-node-skipped",
        ),
    ],
)
def test_render_registration_results_dry_run_title_does_not_claim_success(
    result: tuple[Registration, Outcome | None], *, dry_run: bool
) -> None:
    """Verify a dry run titles the panel 'would register', even when every node is skipped."""
    # Given a recording console
    console = capture_output()

    # When rendering a dry run
    render_registration_results([result], dry_run=dry_run)

    # Then the title does not claim a registration happened
    out = console.export_text()
    assert "Would register 1 volume" in out
    assert "Registered" not in out


@pytest.mark.parametrize(
    ("outcome", "node_names", "expected"),
    [
        pytest.param(DONE, {"n1": "my-node"}, ["data", "my-node", "deleted on"], id="deleted"),
        pytest.param(
            DRY_RUN, {"n1": "node-beta"}, ["data", "would delete on", "node-beta"], id="dry-run"
        ),
        pytest.param(
            Outcome(kind=OutcomeKind.FAILED, error="some error occurred"),
            {"n1": "node-gamma"},
            ["data", "failed on", "some error occurred"],
            id="failed",
        ),
    ],
)
def test_render_deletion_results_leaf_describes_outcome(
    outcome: Outcome, node_names: dict[str, str], expected: list[str]
) -> None:
    """Verify each deletion leaf names the volume, the node by name, and what happened there."""
    # Given a recording console and a registration on node n1
    console = capture_output()
    vol = host_volume_stub("data", node_id="n1", volume_id="vol-1")

    # When rendering one deletion result
    render_deletion_results([(vol, outcome)], node_names=node_names)

    # Then the leaf describes the outcome on the named node
    out = console.export_text()
    for fragment in expected:
        assert fragment in out


def test_render_deletion_results_shows_node_name_under_counted_title() -> None:
    """Verify a deletion shows the node NAME (not the ID) under a title counting deletions."""
    # Given a deleted volume and a node_names map
    console = capture_output()
    vol = host_volume_stub("data", node_id="n1", volume_id="vol-1")

    # When rendering
    render_deletion_results([(vol, DONE)], node_names={"n1": "my-node"})

    # Then the node name replaces the raw ID and the title counts the deleted volume
    out = console.export_text()
    assert "my-node" in out
    assert "n1" not in out
    assert "Deleted 1 volume" in out


def test_render_deletion_results_fallback_to_id_prefix_on_unknown_node() -> None:
    """Verify an unknown node_id falls back to the first 8 chars of the ID."""
    # Given a node_id not present in node_names
    console = capture_output()
    vol = host_volume_stub("data", node_id="abcdef1234567890", volume_id="vol-4")

    # When rendering
    render_deletion_results([(vol, DONE)], node_names={})

    # Then the first 8 chars of the node_id appear as fallback
    assert "abcdef12" in console.export_text()
