"""Tests for the volume command wiring."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import respx

import nd.commands.volume.command as volume_command
from nd.commands.volume import app
from nd.commands.volume.report import VolumeRow
from nd.nomad import NomadConnectionError
from nd.nomad.models.volume import HostVolumeListStub
from nd.volumefiles import VolumeSpec
from tests.builders import host_volume_stub, node_detail, node_stub, to_payload
from tests.helpers import async_return, run_with_client


def _spec(name: str) -> VolumeSpec:
    """Build a host volume spec whose relative path is its name.

    Returns:
        VolumeSpec: The spec.
    """
    return VolumeSpec(
        path=Path(f"/v/{name}.hcl"),
        name=name,
        capabilities=[{"access_mode": "x", "attachment_mode": "file-system"}],
        relative_path=name,
    )


def _discover(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Make volume discovery return one spec per name."""
    specs = [_spec(name) for name in names]
    monkeypatch.setattr(volume_command, "load_volume_directories", list)
    monkeypatch.setattr(volume_command, "discover_volume_files", lambda _dirs: specs)


def _fake_client(
    monkeypatch: pytest.MonkeyPatch, *, registered: list[HostVolumeListStub]
) -> MagicMock:
    """Replace the command's NomadClient with an offline fake listing `registered` volumes.

    Returns:
        MagicMock: The fake client, for asserting on `volumes.delete`.
    """
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.nodes.list = AsyncMock(return_value=[])
    client.volumes.list = AsyncMock(return_value=registered)
    client.volumes.delete = AsyncMock()
    monkeypatch.setattr(volume_command, "NomadClient", lambda _config: client)
    return client


@pytest.fixture
def one_registered_volume(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Discover a `data` spec registered once as `v1`, through an offline fake client.

    Returns:
        MagicMock: The fake client.
    """
    _discover(monkeypatch, "data")
    return _fake_client(monkeypatch, registered=[host_volume_stub("data", volume_id="v1")])


def test_volume_help_lists_subcommands(typer_runner) -> None:
    """Verify `nd volume --help` lists register, delete, and list."""
    # When showing help
    result = typer_runner.invoke(app, ["--help"])

    # Then the three subcommands are present
    assert result.exit_code == 0
    assert "register" in result.stdout
    assert "delete" in result.stdout
    assert "list" in result.stdout


def test_volume_no_args_shows_help(typer_runner) -> None:
    """Verify invoking `nd volume` with no arguments shows help rather than erroring."""
    # When invoking with no arguments
    result = typer_runner.invoke(app, [])

    # Then the help, listing the subcommands, is shown instead of a usage error
    assert "register" in result.stdout
    assert "delete" in result.stdout
    assert "list" in result.stdout


def test_volume_register_dry_run_makes_no_api_calls(
    monkeypatch: pytest.MonkeyPatch, typer_runner
) -> None:
    """Verify register --dry-run plans without registering."""
    # Given one discovered spec, a ready node with storage-root meta, and an offline client
    _discover(monkeypatch, "data")
    node = node_detail(meta={"nfsStorageRoot": "/srv"})
    monkeypatch.setattr(volume_command, "_collect_register_inputs", async_return(([node], [])))
    _fake_client(monkeypatch, registered=[])

    # When running register in dry-run mode, naming the spec so it auto-selects
    result = typer_runner.invoke(app, ["register", "data", "--dry-run"])

    # Then it exits cleanly
    assert result.exit_code == 0


def test_volume_register_no_name_match_exits_one(
    monkeypatch: pytest.MonkeyPatch, typer_runner
) -> None:
    """Verify a register name argument matching no spec exits non-zero before any client call."""
    # Given discovery returns one spec named "data"
    _discover(monkeypatch, "data")

    # When naming a volume that matches nothing
    result = typer_runner.invoke(app, ["register", "zzz"])

    # Then it exits non-zero
    assert result.exit_code == 1


def test_volume_delete_dry_run_with_name_selects_match(
    monkeypatch: pytest.MonkeyPatch, typer_runner
) -> None:
    """Verify delete narrows to the named spec and reports without issuing a delete."""
    # Given two specs and a registration matching the named one
    _discover(monkeypatch, "data", "logs")
    client = _fake_client(monkeypatch, registered=[host_volume_stub("data", volume_id="v1")])

    # When deleting in dry-run mode, naming the matching spec
    result = typer_runner.invoke(app, ["delete", "data", "--dry-run"])

    # Then it exits cleanly and never issues a real delete
    assert result.exit_code == 0
    client.volumes.delete.assert_not_awaited()


def test_volume_delete_aborts_when_user_declines(
    monkeypatch: pytest.MonkeyPatch, typer_runner, one_registered_volume: MagicMock
) -> None:
    """Verify a real delete declined at the confirmation prompt issues no delete."""
    # Given a matching registration and a confirmation prompt the user declines
    monkeypatch.setattr("nd.ui.prompts.select_one", AsyncMock(return_value=False))
    monkeypatch.setattr("nd.ui.prompts.can_prompt", lambda: True)

    # When deleting the named spec without --force
    result = typer_runner.invoke(app, ["delete", "data"])

    # Then it aborts cleanly and never issues a real delete
    assert result.exit_code == 0
    one_registered_volume.volumes.delete.assert_not_awaited()


def test_volume_delete_force_skips_confirmation(
    monkeypatch: pytest.MonkeyPatch, typer_runner, one_registered_volume: MagicMock
) -> None:
    """Verify --force deletes without prompting for confirmation."""
    # Given a matching registration and a confirmation prompt that must not be reached
    prompt = AsyncMock(return_value=False)
    monkeypatch.setattr("nd.ui.prompts.select_one", prompt)

    # When deleting the named spec with --force
    result = typer_runner.invoke(app, ["delete", "data", "--force"])

    # Then it deletes the registration without ever prompting
    assert result.exit_code == 0
    prompt.assert_not_awaited()
    one_registered_volume.volumes.delete.assert_awaited_once_with("v1")


@pytest.mark.parametrize(
    ("error", "expected_exception"),
    [
        (NomadConnectionError("connection refused"), None),
        (RuntimeError("bug"), RuntimeError),
    ],
)
def test_volume_delete_reports_nomad_failures_and_propagates_others(
    typer_runner,
    one_registered_volume: MagicMock,
    error: Exception,
    expected_exception: type[Exception] | None,
) -> None:
    """Verify a Nomad error on one delete is reported in place while any other error propagates."""
    # Given a matching registration whose delete call fails
    one_registered_volume.volumes.delete = AsyncMock(side_effect=error)

    # When deleting the named spec with --force
    result = typer_runner.invoke(app, ["delete", "data", "--force"])

    # Then a Nomad failure exits cleanly after reporting, and any other error escapes
    if expected_exception is None:
        assert result.exit_code == 0
    else:
        assert isinstance(result.exception, expected_exception)


def test_volume_list_joins_named_specs_to_registrations(
    monkeypatch: pytest.MonkeyPatch, typer_runner, httpx2_mock: respx.Router, nomad_env: str
) -> None:
    """Verify `nd volume list NAME` narrows specs and shows each one's registered node names."""
    # Given two specs, a cluster node, and a registration of one spec on that node
    _discover(monkeypatch, "data", "logs")
    httpx2_mock.get(f"{nomad_env}/v1/nodes").respond(
        json=[to_payload(node_stub("node1", node_id="n1-0000-0000"))]
    )
    httpx2_mock.get(f"{nomad_env}/v1/volumes").respond(
        json=[to_payload(host_volume_stub("data", node_id="n1-0000-0000", volume_id="v1"))]
    )
    rendered: list[list[VolumeRow]] = []
    monkeypatch.setattr(volume_command, "render_list", rendered.append)

    # When listing volumes, naming the "data" spec
    result = typer_runner.invoke(app, ["list", "data"])

    # Then only the named spec is shown, registered on the node by name
    assert result.exit_code == 0
    assert rendered == [[VolumeRow(name="data", nodes=["node1"], registered=True)]]


def test_collect_register_inputs_reads_only_ready_nodes(
    httpx2_mock: respx.Router, nomad_env: str
) -> None:
    """Verify registration reads full records only for ready nodes, skipping down ones."""
    # Given one ready node, one down node, and no registered volumes
    httpx2_mock.get(f"{nomad_env}/v1/nodes").respond(
        json=[
            to_payload(node_stub("up", node_id="n-up")),
            to_payload(node_stub("down", node_id="n-down", status="down")),
        ]
    )
    httpx2_mock.get(f"{nomad_env}/v1/volumes").respond(json=[])
    httpx2_mock.get(f"{nomad_env}/v1/node/n-up").respond(
        json=to_payload(node_detail("up", node_id="n-up"))
    )
    # No route for n-down, so reading it fails the test as an unmocked request

    # When collecting the registration inputs
    nodes, registered = run_with_client(volume_command._collect_register_inputs)

    # Then only the ready node is returned
    assert [node.id for node in nodes] == ["n-up"]
    assert registered == []
