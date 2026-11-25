"""Typer wiring and async orchestration for ``nd volume``."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated

import typer
from nclutils import pp

from nd.commands._common import ForceOption, VerboseOption, configure_verbosity, dry_run_option
from nd.commands.volume.render import (
    render_deletion_results,
    render_list,
    render_registration_results,
)
from nd.commands.volume.report import (
    DONE,
    DRY_RUN,
    Outcome,
    OutcomeKind,
    build_list_rows,
    build_register_payload,
    plan_deletions,
    plan_registrations,
)
from nd.nodes import node_names_by_id
from nd.nomad import NomadClient, NomadConfig, NomadError
from nd.targets import job_file_label, resolve_targets, select_targets
from nd.ui.prompts import FORCE_REMEDY, confirm
from nd.volumefiles import discover_volume_files, load_volume_directories

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

    from nd.commands.volume.report import Registration
    from nd.nomad.models.node import Node
    from nd.nomad.models.volume import HostVolumeListStub
    from nd.volumefiles import VolumeSpec

app = typer.Typer(
    help="Manage Nomad dynamic host volumes: register, delete, and list host volume specs.",
    no_args_is_help=True,
)

DryRunOption = Annotated[bool, dry_run_option("Report actions without changing the cluster.")]
NameArgument = Annotated[
    str | None,
    typer.Argument(help="Volume to act on; matches any spec whose name contains this."),
]


async def _collect_register_inputs(
    client: NomadClient,
) -> tuple[list[Node], list[HostVolumeListStub]]:
    """Fetch nodes (with per-node meta) and the registered host volumes concurrently.

    Split out as a named coroutine so tests can monkeypatch it as the single
    data-collection seam, running the command fully offline.
    """
    stubs, registered = await asyncio.gather(client.nodes.list(), client.volumes.list())
    # Only ready nodes get registrations, so only they need the full record's meta.
    nodes = await asyncio.gather(*(client.nodes.read(s.id) for s in stubs if s.status == "ready"))
    return list(nodes), registered


async def _attempt_all(attempts: Sequence[Awaitable[object]]) -> list[Outcome]:
    """Run per-node volume calls concurrently and report each one's outcome in order.

    A Nomad failure on one node becomes that node's failed outcome so the rest still
    run and report; any other exception is a bug and propagates.

    Args:
        attempts: The register or delete calls, one per node.

    Returns:
        list[Outcome]: One outcome per attempt, in the order given.
    """
    settled = await asyncio.gather(*attempts, return_exceptions=True)
    outcomes: list[Outcome] = []
    for result in settled:
        if isinstance(result, NomadError):
            outcomes.append(Outcome(kind=OutcomeKind.FAILED, error=str(result)))
        elif isinstance(result, BaseException):
            raise result
        else:
            outcomes.append(DONE)
    return outcomes


@app.command()
def register(
    ctx: typer.Context,
    name: NameArgument = None,
    dry_run: DryRunOption = False,  # noqa: FBT002
    verbose: VerboseOption = 0,
) -> None:
    """Register discovered host volumes on every eligible node.

    Reads host volume specs from the volume directories in your nd config, then
    registers each selected spec on every ready node. A node is skipped when it lacks
    the nfsStorageRoot meta, when the spec has no relative_path, or when the volume is
    already registered there. Use --dry-run to preview without touching the cluster.
    """
    configure_verbosity(ctx, verbose)
    asyncio.run(_run_register(name_arg=name, dry_run=dry_run))


@app.command()
def delete(
    ctx: typer.Context,
    name: NameArgument = None,
    force: ForceOption = False,  # noqa: FBT002
    dry_run: DryRunOption = False,  # noqa: FBT002
    verbose: VerboseOption = 0,
) -> None:
    """Delete registered host volumes matching the selected specs.

    Matches the selected specs against the volumes currently registered on the
    cluster and deletes every registration whose name matches a spec. Deleting a
    host volume is irreversible, so a real delete confirms first unless --force is
    given. Use --dry-run to preview which registrations would be removed.
    """
    configure_verbosity(ctx, verbose)
    asyncio.run(_run_delete(name_arg=name, force=force, dry_run=dry_run))


@app.command(name="list")
def list_(ctx: typer.Context, name: NameArgument = None, verbose: VerboseOption = 0) -> None:
    """List host volume specs and where each is registered.

    Joins the host volume specs from your nd config to the registrations on the
    cluster, showing each spec and the nodes it is registered on. This view is
    read-only and never prompts.
    """
    configure_verbosity(ctx, verbose)
    asyncio.run(_run_list(name_arg=name))


async def _select_specs(name_arg: str | None, action: str) -> list[VolumeSpec]:
    """Discover specs and resolve the optional name argument to a non-empty selection.

    Shared by ``register`` and ``delete`` so both narrow to an optional name the same
    way ``run``/``stop`` do. No specs configured exits 0 here; ``select_targets``
    handles the cancelled prompt and the unmatched name.
    """
    specs = discover_volume_files(load_volume_directories())
    if not specs:
        pp.info("No host volume specs found; set [volumes] directories in your nd config.")
        raise typer.Exit(0)
    return await select_targets(
        specs,
        name_arg,
        name_of=lambda s: s.name,
        label_of=lambda s: job_file_label(name=s.name, path=s.path),
        prompt=f"Select volumes to {action}",
        miss_noun="host volume spec",
        remedy="name a volume explicitly",
    )


async def _run_register(*, name_arg: str | None, dry_run: bool) -> None:
    """Discover specs, plan registrations, and register (unless dry-run).

    Registrations run concurrently. Dry-run renders the same tree with "would
    register" leaves so the output matches a real run.
    """
    specs = await _select_specs(name_arg, "register")
    config = NomadConfig.resolve()
    async with NomadClient(config) as client:
        nodes, registered = await _collect_register_inputs(client)
        plan = plan_registrations(specs=specs, nodes=nodes, registered=registered)
        if not plan:
            pp.info("No eligible nodes to register host volumes on.")
            return
        attempts = (
            []
            if dry_run
            else [
                client.volumes.register(
                    build_register_payload(
                        spec=reg.spec, node_id=reg.node_id, host_path=reg.host_path
                    )
                )
                for reg in plan
                if reg.host_path is not None
            ]
        )
        attempted = iter(await _attempt_all(attempts))
    results: list[tuple[Registration, Outcome | None]] = [
        (reg, None if reg.is_skipped else DRY_RUN if dry_run else next(attempted)) for reg in plan
    ]
    render_registration_results(results, dry_run=dry_run)


async def _confirm_delete(to_delete: list[HostVolumeListStub]) -> bool:
    """Ask the user to confirm deleting the matched host volume registrations.

    Deleting a dynamic host volume is irreversible and orphans data for any job that
    mounts it, so a real delete confirms before touching the cluster unless --force is
    passed. The prompt names the distinct volumes so the user sees exactly what goes.
    """
    names = ", ".join(sorted({vol.name for vol in to_delete}))
    return await confirm(
        f"Delete {len(to_delete)} host volume registration(s) ({names})? This cannot be undone.",
        remedy=FORCE_REMEDY,
    )


async def _run_delete(*, name_arg: str | None, force: bool, dry_run: bool) -> None:
    """Discover specs, find matching registrations, and delete (unless dry-run).

    Fetches node names so deletion trees show human-readable names rather than
    node GUIDs. A real delete confirms first unless ``force`` is set; dry-run never
    prompts. Deletes run concurrently; dry-run renders the same tree with "would
    delete" leaves so the output matches a real run.
    """
    specs = await _select_specs(name_arg, "delete")
    config = NomadConfig.resolve()
    async with NomadClient(config) as client:
        node_names, registered = await asyncio.gather(
            node_names_by_id(client), client.volumes.list()
        )
        to_delete = plan_deletions(specs=specs, registered=registered)
        if not to_delete:
            pp.info("No registered host volumes match the selected specs.")
            return
        if not dry_run and not force and not await _confirm_delete(to_delete):
            pp.info("Aborted")
            return
        outcomes = (
            [DRY_RUN] * len(to_delete)
            if dry_run
            else await _attempt_all([client.volumes.delete(vol.id) for vol in to_delete])
        )
    render_deletion_results(list(zip(to_delete, outcomes, strict=True)), node_names=node_names)


async def _run_list(*, name_arg: str | None) -> None:
    """Discover specs, fetch nodes and registrations concurrently, and render the joined table.

    A name argument narrows the listed specs by name substring; with none, every spec is
    shown. Unlike ``register``/``delete`` this read-only view never prompts, so a bare
    ``nd volume list`` stays a one-shot table.
    """
    specs = discover_volume_files(load_volume_directories())
    targets = resolve_targets(specs, name_arg, name_of=lambda s: s.name).candidates
    config = NomadConfig.resolve()
    async with NomadClient(config) as client:
        node_names, registered = await asyncio.gather(
            node_names_by_id(client), client.volumes.list()
        )
    render_list(build_list_rows(specs=targets, registered=registered, node_names=node_names))
