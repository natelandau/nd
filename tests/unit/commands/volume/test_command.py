"""Tests for the volume command wiring."""

from collections.abc import Callable
from pathlib import Path

import pytest
import respx

import nd.commands.volume.command as volume_command
from nd.commands.volume import app
from nd.commands.volume.report import VolumeRow
from tests.builders import host_volume_stub, node_detail, node_stub, to_payload
from tests.conftest import PromptAnswers
from tests.helpers import run_with_client

WRITE_METHODS = {"POST", "PUT", "DELETE"}


def _write_requests(httpx2_mock: respx.Router) -> list[str]:
    """List the method and URL of every request that would change the cluster.

    Returns:
        list[str]: One `METHOD URL` entry per write request sent.
    """
    return [
        f"{call.request.method} {call.request.url}"
        for call in httpx2_mock.calls
        if call.request.method in WRITE_METHODS
    ]


def _mock_one_registered_volume(httpx2_mock: respx.Router, nomad_env: str) -> None:
    """Mock a cluster with one node and a `data` volume registered on it as `v1`."""
    httpx2_mock.get(f"{nomad_env}/v1/nodes").respond(
        json=[to_payload(node_stub("node1", node_id="n1"))]
    )
    httpx2_mock.get(f"{nomad_env}/v1/volumes").respond(
        json=[to_payload(host_volume_stub("data", node_id="n1", volume_id="v1"))]
    )


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


def test_volume_register_dry_run_sends_no_writes(
    typer_runner,
    httpx2_mock: respx.Router,
    nomad_env: str,
    volume_files: Callable[[str], Path],
) -> None:
    """Verify register --dry-run plans without registering."""
    # Given one spec, a ready node with storage-root meta, and no registered volumes
    volume_files("data")
    httpx2_mock.get(f"{nomad_env}/v1/nodes").respond(
        json=[to_payload(node_stub("node1", node_id="n1"))]
    )
    httpx2_mock.get(f"{nomad_env}/v1/node/n1").respond(
        json=to_payload(node_detail("node1", node_id="n1", meta={"nfsStorageRoot": "/srv"}))
    )
    httpx2_mock.get(f"{nomad_env}/v1/volumes").respond(json=[])

    # When running register in dry-run mode, naming the spec so it auto-selects
    result = typer_runner.invoke(app, ["register", "data", "--dry-run"])

    # Then it exits cleanly without sending any registration
    assert result.exit_code == 0
    assert _write_requests(httpx2_mock) == []


def test_volume_register_no_name_match_exits_one(
    typer_runner, volume_files: Callable[[str], Path]
) -> None:
    """Verify a register name argument matching no spec exits non-zero before any client call."""
    # Given one spec named "data" and no mocked cluster
    volume_files("data")

    # When naming a volume that matches nothing
    result = typer_runner.invoke(app, ["register", "zzz"])

    # Then it exits non-zero
    assert result.exit_code == 1


def test_volume_delete_dry_run_with_name_selects_match(
    typer_runner,
    httpx2_mock: respx.Router,
    nomad_env: str,
    volume_files: Callable[[str], Path],
) -> None:
    """Verify delete narrows to the named spec and reports without issuing a delete."""
    # Given two specs and a registration matching the named one
    volume_files("data")
    volume_files("logs")
    _mock_one_registered_volume(httpx2_mock, nomad_env)

    # When deleting in dry-run mode, naming the matching spec
    result = typer_runner.invoke(app, ["delete", "data", "--dry-run"])

    # Then it exits cleanly and never issues a real delete
    assert result.exit_code == 0
    assert _write_requests(httpx2_mock) == []


def test_volume_delete_aborts_when_user_declines(
    typer_runner,
    httpx2_mock: respx.Router,
    nomad_env: str,
    volume_files: Callable[[str], Path],
    interactive_session: PromptAnswers,
) -> None:
    """Verify a real delete declined at the confirmation prompt issues no delete."""
    # Given a matching registration and a confirmation prompt the user declines
    volume_files("data")
    _mock_one_registered_volume(httpx2_mock, nomad_env)
    interactive_session.choice = False

    # When deleting the named spec without --force
    result = typer_runner.invoke(app, ["delete", "data"])

    # Then it aborts cleanly and never issues a real delete
    assert result.exit_code == 0
    assert _write_requests(httpx2_mock) == []


def test_volume_delete_force_skips_confirmation(
    typer_runner,
    httpx2_mock: respx.Router,
    nomad_env: str,
    volume_files: Callable[[str], Path],
    interactive_session: PromptAnswers,
) -> None:
    """Verify --force deletes without prompting for confirmation."""
    # Given a matching registration and a confirmation prompt that would decline if reached
    volume_files("data")
    _mock_one_registered_volume(httpx2_mock, nomad_env)
    delete_route = httpx2_mock.delete(f"{nomad_env}/v1/volume/host/v1/delete")
    delete_route.respond(json={})
    interactive_session.choice = False

    # When deleting the named spec with --force
    result = typer_runner.invoke(app, ["delete", "data", "--force"])

    # Then it deletes the registration without being stopped by the prompt
    assert result.exit_code == 0
    assert delete_route.call_count == 1


def test_volume_delete_reports_nomad_failure_and_exits_zero(
    typer_runner,
    httpx2_mock: respx.Router,
    nomad_env: str,
    volume_files: Callable[[str], Path],
) -> None:
    """Verify a Nomad error on one delete is reported in place instead of aborting the command."""
    # Given a matching registration whose delete the cluster rejects
    volume_files("data")
    _mock_one_registered_volume(httpx2_mock, nomad_env)
    delete_route = httpx2_mock.delete(f"{nomad_env}/v1/volume/host/v1/delete")
    delete_route.respond(status_code=500, text="internal error")

    # When deleting the named spec with --force
    result = typer_runner.invoke(app, ["delete", "data", "--force"])

    # Then the failure is reported and the command exits cleanly
    assert result.exit_code == 0
    assert delete_route.call_count == 1


def test_volume_delete_propagates_non_nomad_errors(
    typer_runner,
    httpx2_mock: respx.Router,
    nomad_env: str,
    volume_files: Callable[[str], Path],
) -> None:
    """Verify an error that is not a Nomad error escapes the delete instead of being reported."""
    # Given a matching registration whose delete raises a programming error
    volume_files("data")
    _mock_one_registered_volume(httpx2_mock, nomad_env)
    delete_route = httpx2_mock.delete(f"{nomad_env}/v1/volume/host/v1/delete")
    delete_route.side_effect = RuntimeError("bug")

    # When deleting the named spec with --force
    result = typer_runner.invoke(app, ["delete", "data", "--force"])

    # Then the error escapes the command
    assert isinstance(result.exception, RuntimeError)


def test_volume_list_joins_named_specs_to_registrations(
    monkeypatch: pytest.MonkeyPatch,
    typer_runner,
    httpx2_mock: respx.Router,
    nomad_env: str,
    volume_files: Callable[[str], Path],
) -> None:
    """Verify `nd volume list NAME` narrows specs and shows each one's registered node names."""
    # Given two specs, a cluster node, and a registration of one spec on that node
    volume_files("data")
    volume_files("logs")
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
