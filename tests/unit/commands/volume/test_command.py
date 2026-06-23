"""Tests for the volume command wiring."""

from typer.testing import CliRunner

from nd.commands.volume import app

runner = CliRunner()


def test_volume_help_lists_subcommands() -> None:
    """Verify `nd volume --help` lists register, delete, and list."""
    # When showing help
    result = runner.invoke(app, ["--help"])
    # Then the three subcommands are present
    assert result.exit_code == 0
    assert "register" in result.stdout
    assert "delete" in result.stdout
    assert "list" in result.stdout


def test_volume_help_shows_group_description() -> None:
    """Verify `nd volume --help` includes the group-level description."""
    # When requesting help for the volume group
    result = runner.invoke(app, ["--help"])
    # Then the group description mentioning dynamic host volumes is shown
    assert result.exit_code == 0
    assert "dynamic host volumes" in result.stdout


def test_volume_no_args_shows_help() -> None:
    """Verify invoking `nd volume` with no arguments shows help rather than erroring."""
    # When invoking with no arguments (no_args_is_help=True)
    result = runner.invoke(app, [])
    # Then the output contains the group description (help is shown, not a usage error)
    assert "dynamic host volumes" in result.stdout


def test_volume_register_dry_run_makes_no_api_calls(monkeypatch) -> None:
    """Verify register --dry-run plans without registering."""
    # Given discovery returns one spec and a fake client/nodes with meta
    from pathlib import Path

    import nd.commands.volume.command as cmd
    from nd.volumefiles import VolumeSpec

    spec = VolumeSpec(
        path=Path("/v/data.hcl"),
        name="data",
        capabilities=[{"access_mode": "x", "attachment_mode": "file-system"}],
        relative_path="data",
    )
    monkeypatch.setattr(cmd, "load_volume_directories", list)
    monkeypatch.setattr(cmd, "discover_volume_files", lambda dirs: [spec])

    # Stub the async cluster fetch so no network or registration happens
    async def _fake_collect(client) -> tuple:
        from nd.nomad.models.node import Node

        node = Node(
            id="n1",
            datacenter="dc1",
            name="node1",
            node_class="",
            node_pool="default",
            status="ready",
            drain=False,
            scheduling_eligibility="eligible",
            http_addr="10.0.0.1:4646",
            tls_enabled=False,
            meta={"nfsStorageRoot": "/srv"},
            create_index=1,
            modify_index=2,
        )
        return [node], []

    monkeypatch.setattr(cmd, "_collect_register_inputs", _fake_collect)

    # Stub the NomadClient so no network connection is attempted
    from unittest.mock import AsyncMock, MagicMock

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(cmd.NomadClient, "from_config", lambda cfg: fake_client)
    monkeypatch.setattr(cmd.NomadConfig, "resolve", lambda: MagicMock(ui_base="http://test:4646"))

    # When running register in dry-run mode, naming the spec so it auto-selects
    result = runner.invoke(app, ["register", "data", "--dry-run"])

    # Then it exits cleanly
    assert result.exit_code == 0


def test_volume_register_no_name_match_exits_one(monkeypatch) -> None:
    """Verify a register name argument matching no spec exits non-zero before any client call."""
    # Given discovery returns one spec named "data"
    from pathlib import Path

    import nd.commands.volume.command as cmd
    from nd.volumefiles import VolumeSpec

    spec = VolumeSpec(
        path=Path("/v/data.hcl"),
        name="data",
        capabilities=[{"access_mode": "x", "attachment_mode": "file-system"}],
        relative_path="data",
    )
    monkeypatch.setattr(cmd, "load_volume_directories", list)
    monkeypatch.setattr(cmd, "discover_volume_files", lambda dirs: [spec])

    # When naming a volume that matches nothing
    result = runner.invoke(app, ["register", "zzz"])

    # Then it exits non-zero
    assert result.exit_code == 1


def test_volume_delete_dry_run_with_name_selects_match(monkeypatch) -> None:
    """Verify delete narrows to the named spec and reports without issuing a delete."""
    # Given two specs and a registration matching the named one
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock

    import msgspec

    import nd.commands.volume.command as cmd
    from nd.nomad.models.volume import HostVolumeListStub
    from nd.volumefiles import VolumeSpec

    specs = [
        VolumeSpec(path=Path("/v/data.hcl"), name="data", capabilities=[], relative_path="data"),
        VolumeSpec(path=Path("/v/logs.hcl"), name="logs", capabilities=[], relative_path="logs"),
    ]
    monkeypatch.setattr(cmd, "load_volume_directories", list)
    monkeypatch.setattr(cmd, "discover_volume_files", lambda dirs: specs)

    registered = msgspec.convert(
        {"ID": "v1", "Name": "data", "NodeID": "n1", "State": "ready"},
        type=HostVolumeListStub,
    )
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.nodes.list = AsyncMock(return_value=[])
    fake_client.volumes.list = AsyncMock(return_value=[registered])
    fake_client.volumes.delete = AsyncMock()
    monkeypatch.setattr(cmd.NomadClient, "from_config", lambda cfg: fake_client)
    monkeypatch.setattr(cmd.NomadConfig, "resolve", lambda: MagicMock())

    # When deleting in dry-run mode, naming the matching spec
    result = runner.invoke(app, ["delete", "data", "--dry-run"])

    # Then it exits cleanly and never issues a real delete
    assert result.exit_code == 0
    fake_client.volumes.delete.assert_not_awaited()
