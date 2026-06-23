"""Typer wiring and async orchestration for ``nd volume``."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated

import typer
from nclutils import pp

from nd.commands._common import VerboseOption, configure_verbosity
from nd.commands.volume.render import (
    render_deletion_results,
    render_list,
    render_registration_results,
)
from nd.commands.volume.report import (
    build_list_rows,
    build_register_payload,
    plan_deletions,
    plan_registrations,
)
from nd.nomad import NomadClient, NomadConfig
from nd.targets import resolve_targets, select_candidates
from nd.volumefiles import discover_volume_files, load_volume_directories

if TYPE_CHECKING:
    from nd.commands.volume.report import Registration
    from nd.nomad.models.node import Node
    from nd.nomad.models.volume import HostVolumeListStub
    from nd.volumefiles import VolumeSpec

app = typer.Typer(
    help="Manage Nomad dynamic host volumes: register, delete, and list host volume specs.",
    no_args_is_help=True,
)

DryRunOption = Annotated[
    bool, typer.Option("--dry-run", "-n", help="Report actions without changing the cluster.")
]
NameArgument = Annotated[
    str | None,
    typer.Argument(help="Volume to act on; matches any spec whose name starts with this."),
]


def _volume_label(spec: VolumeSpec) -> str:
    """Render a volume spec's prompt line as ``<name>  [<file>]``."""
    return f"{spec.name}  [{spec.path.name}]"


async def _collect_register_inputs(
    client: NomadClient,
) -> tuple[list[Node], list[HostVolumeListStub]]:
    """Fetch nodes (with per-node meta) and the registered host volumes concurrently.

    Split out as a named coroutine so tests can monkeypatch it as the single
    data-collection seam, running the command fully offline.
    """
    stubs = await client.nodes.list()
    nodes, registered = await asyncio.gather(
        asyncio.gather(*(client.nodes.read(s.id) for s in stubs)),
        client.volumes.list(),
    )
    return list(nodes), registered


@app.command()
def register(
    ctx: typer.Context,
    name: NameArgument = None,
    dry_run: DryRunOption = False,  # noqa: FBT002
    verbose: VerboseOption = 0,
) -> None:
    """Register discovered host volumes on every eligible node."""
    configure_verbosity(ctx, verbose)
    asyncio.run(_run_register(name_arg=name, dry_run=dry_run))


@app.command()
def delete(
    ctx: typer.Context,
    name: NameArgument = None,
    dry_run: DryRunOption = False,  # noqa: FBT002
    verbose: VerboseOption = 0,
) -> None:
    """Delete registered host volumes matching the selected specs."""
    configure_verbosity(ctx, verbose)
    asyncio.run(_run_delete(name_arg=name, dry_run=dry_run))


@app.command(name="list")
def list_(ctx: typer.Context, name: NameArgument = None, verbose: VerboseOption = 0) -> None:
    """List host volume specs and where each is registered."""
    configure_verbosity(ctx, verbose)
    asyncio.run(_run_list(name_arg=name))


async def _select_specs(name_arg: str | None, action: str) -> list[VolumeSpec]:
    """Discover specs and resolve the optional name argument to a non-empty selection.

    Shared by ``register`` and ``delete`` so both narrow to an optional name the same
    way ``run``/``stop`` do: a missing name offers every spec for a multi-select, a
    prefix auto-selects a lone match or prompts among several. Always returns at least
    one spec; the three terminal cases raise ``typer.Exit`` here (rather than each
    caller re-decoding a tristate): no specs configured or a cancelled prompt exit 0,
    a name that matched nothing reports the miss and exits 1.
    """
    specs = discover_volume_files(load_volume_directories())
    if not specs:
        pp.info("No host volume specs found; set [volumes] directories in your nd config.")
        raise typer.Exit(0)
    resolution = resolve_targets(specs, name_arg, name_of=lambda s: s.name)
    targets = await select_candidates(
        resolution, f"Select volumes to {action}", label_of=_volume_label
    )
    if targets is None:
        raise typer.Exit(0)
    if not targets:
        pp.error(f"No host volume spec matching '{name_arg}'")
        raise typer.Exit(1)
    return targets


async def _run_register(*, name_arg: str | None, dry_run: bool) -> None:
    """Discover specs, plan registrations, and register (unless dry-run).

    In dry-run mode the planned actions are collected with a ``"dryrun"`` outcome
    and rendered as a tree so the output is consistent with a real run.
    """
    specs = await _select_specs(name_arg, "register")
    config = NomadConfig.resolve()
    async with NomadClient.from_config(config) as client:
        nodes, registered = await _collect_register_inputs(client)
        plan = plan_registrations(specs=specs, nodes=nodes, registered=registered)
        if not plan:
            pp.info("No eligible nodes to register host volumes on.")
            return
        results: list[tuple[Registration, str]] = []
        for reg in plan:
            if reg.action == "skip":
                results.append((reg, "skip"))
                continue
            if dry_run:
                results.append((reg, "dryrun"))
                continue
            try:
                payload = build_register_payload(
                    spec=reg.spec, node_id=reg.node_id, host_path=reg.host_path or ""
                )
                await client.volumes.register(payload)
                results.append((reg, "ok"))
            except Exception as exc:  # noqa: BLE001 - surface any per-node failure, continue
                results.append((reg, str(exc)))
    render_registration_results(results)


async def _run_delete(*, name_arg: str | None, dry_run: bool) -> None:
    """Discover specs, find matching registrations, and delete (unless dry-run).

    Fetches node names so deletion trees show human-readable names rather than
    node GUIDs. In dry-run mode volumes are collected with a ``"would-delete"``
    outcome and rendered as a tree consistent with a real run.
    """
    specs = await _select_specs(name_arg, "delete")
    config = NomadConfig.resolve()
    async with NomadClient.from_config(config) as client:
        nodes, registered = await asyncio.gather(client.nodes.list(), client.volumes.list())
        to_delete = plan_deletions(specs=specs, registered=registered)
        if not to_delete:
            pp.info("No registered host volumes match the selected specs.")
            return
        node_names: dict[str, str] = {n.id: n.name for n in nodes}
        results: list[tuple[HostVolumeListStub, str]] = []
        for vol in to_delete:
            if dry_run:
                results.append((vol, "would-delete"))
                continue
            try:
                await client.volumes.delete(vol.id)
                results.append((vol, "deleted"))
            except Exception as exc:  # noqa: BLE001 - surface any per-volume failure, continue
                results.append((vol, str(exc)))
    render_deletion_results(results, node_names=node_names)


async def _run_list(*, name_arg: str | None) -> None:
    """Discover specs, fetch nodes and registrations concurrently, and render the joined table.

    A name argument narrows the listed specs by name prefix; with none, every spec is
    shown. Unlike ``register``/``delete`` this read-only view never prompts, so a bare
    ``nd volume list`` stays a one-shot table.
    """
    specs = discover_volume_files(load_volume_directories())
    targets = resolve_targets(specs, name_arg, name_of=lambda s: s.name).candidates
    config = NomadConfig.resolve()
    async with NomadClient.from_config(config) as client:
        nodes, registered = await asyncio.gather(client.nodes.list(), client.volumes.list())
    node_names = {n.id: n.name for n in nodes}
    render_list(build_list_rows(specs=targets, registered=registered, node_names=node_names))
