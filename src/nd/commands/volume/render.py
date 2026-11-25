"""Rich rendering for ``nd volume``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nclutils import pp
from rich.console import Group
from rich.tree import Tree

from nd.commands.volume.report import ALREADY_REGISTERED_REASON, OutcomeKind
from nd.nodes import node_label
from nd.ui.panels import status_table, titled_panel
from nd.ui.text import plural

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from rich.console import RenderableType

    from nd.commands.volume.report import Outcome, Registration, VolumeRow
    from nd.nomad.models.volume import HostVolumeListStub


def _any_dry_run(outcomes: Iterable[Outcome | None]) -> bool:
    """Report whether any outcome is a dry run, so a title never claims a change it skipped."""
    return any(outcome is not None and outcome.kind is OutcomeKind.DRY_RUN for outcome in outcomes)


def _print_grouped_leaves(leaves: list[tuple[str, str]], *, verb: str) -> None:
    """Print one tree per volume, stacked in one titled panel and blank-line separated.

    Mirrors the framed result panels of ``nd run``/``nd stop`` so every command
    speaks the same visual language.

    Args:
        leaves: Pairs of (volume name, leaf markup); volumes keep first-seen order.
        verb: The title's leading verb, such as ``Registered`` or ``Would delete``.
    """
    trees: dict[str, Tree] = {}
    for volume, leaf in leaves:
        trees.setdefault(volume, Tree(f"[bold]{volume}[/]")).add(leaf)
    if not trees:
        return
    body: list[RenderableType] = []
    for index, tree in enumerate(trees.values()):
        if index:
            body.append("")
        body.append(tree)
    title = f"{verb} {plural(count=len(trees), noun='volume')}"
    pp.console().print(titled_panel(Group(*body), title))


def render_list(rows: list[VolumeRow]) -> None:
    """Print the host-volume table inside a titled panel with plain node names.

    Node names are shown as plain text rather than hyperlinks because the list view
    is keyed on volumes, not nodes, and linking each name to a GUID-based URL would
    add noise without aiding navigation.
    """
    if not rows:
        pp.info("No host volume specs found; set [volumes] directories in your nd config.")
        return
    table = status_table("VOLUME", "REGISTERED", "NODES")
    for row in rows:
        state = "[green]✓ registered[/]" if row.registered else "[dim]• not registered[/]"
        nodes = ", ".join(row.nodes) if row.nodes else "[dim]-[/]"
        table.add_row(row.name, state, nodes)
    pp.console().print(titled_panel(table, "Host volumes"))


def _registration_leaf(reg: Registration, outcome: Outcome | None) -> str:
    """Return Rich markup for one node's registration result.

    Args:
        reg: The planned registration, carrying node name, host path, and skip reason.
        outcome: The register attempt's outcome, or None for a skipped node.

    Returns:
        str: A Rich markup string for use as a tree leaf label.
    """
    if outcome is None:
        if reg.reason == ALREADY_REGISTERED_REASON:
            return f"[dim]• already registered on {reg.node_name}[/]"
        return f"[yellow]- skipped on {reg.node_name}: {reg.reason}[/]"
    if outcome.kind is OutcomeKind.DONE:
        return f"[green]✓ registered on {reg.node_name} at {reg.host_path}[/]"
    if outcome.kind is OutcomeKind.DRY_RUN:
        return f"[cyan]→ would register on {reg.node_name} at {reg.host_path}[/]"
    return f"[red]✗ failed on {reg.node_name}: {outcome.error}[/]"


def render_registration_results(
    results: Sequence[tuple[Registration, Outcome | None]], *, dry_run: bool = False
) -> None:
    """Print a per-volume tree showing each node's registration outcome.

    Args:
        results: Pairs of (Registration, outcome) in plan order; the outcome is None
            for a node the plan skips.
        dry_run: Whether nothing was registered, so the title says so even when the
            plan skips every node.
    """
    dry = dry_run or _any_dry_run(o for _, o in results)
    verb = "Would register" if dry else "Registered"
    _print_grouped_leaves(
        [(reg.spec.name, _registration_leaf(reg, outcome)) for reg, outcome in results],
        verb=verb,
    )


def _deletion_leaf(vol: HostVolumeListStub, outcome: Outcome, node_names: dict[str, str]) -> str:
    """Return Rich markup for one registration's deletion result.

    Args:
        vol: The registered host volume being deleted.
        outcome: The delete attempt's outcome.
        node_names: Node names keyed by node ID; unknown IDs fall back to a short ID.

    Returns:
        str: A Rich markup string for use as a tree leaf label.
    """
    name = node_label(node_names=node_names, node_id=vol.node_id)
    if outcome.kind is OutcomeKind.DONE:
        return f"[green]✓ deleted on {name}[/]"
    if outcome.kind is OutcomeKind.DRY_RUN:
        return f"[cyan]→ would delete on {name}[/]"
    return f"[red]✗ failed on {name}: {outcome.error}[/]"


def render_deletion_results(
    results: Sequence[tuple[HostVolumeListStub, Outcome]],
    *,
    node_names: dict[str, str],
) -> None:
    """Print a per-volume tree showing each registration's deletion outcome.

    Args:
        results: Pairs of (HostVolumeListStub, outcome) in plan order.
        node_names: Node names keyed by node ID, for human-readable leaves.
    """
    verb = "Would delete" if _any_dry_run(o for _, o in results) else "Deleted"
    _print_grouped_leaves(
        [(vol.name, _deletion_leaf(vol, outcome, node_names)) for vol, outcome in results],
        verb=verb,
    )
