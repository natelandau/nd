"""Rich rendering for ``nd volume``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nclutils import pp
from rich.console import Group
from rich.tree import Tree

from nd.commands.volume.report import ALREADY_REGISTERED_REASON
from nd.ui.panels import status_table, titled_panel

if TYPE_CHECKING:
    from rich.console import RenderableType

    from nd.commands.volume.report import Registration, VolumeRow
    from nd.nomad.models.volume import HostVolumeListStub


def _print_volume_groups(title: str, trees: list[Tree]) -> None:
    """Print per-volume trees stacked in one titled panel, blank-line separated.

    Mirrors the framed result panels of ``nd run``/``nd stop`` so every command
    speaks the same visual language, and the blank line between groups gives each
    volume room to breathe instead of crowding the next one.
    """
    if not trees:
        return
    body: list[RenderableType] = []
    for index, tree in enumerate(trees):
        if index:
            body.append("")  # blank line so adjacent volume groups stay distinct
        body.append(tree)
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


def _registration_leaf(reg: Registration, outcome: str) -> str:
    """Return Rich markup for a single registration result leaf.

    The leaf style reflects whether the action succeeded, was a dry-run,
    was already registered (dim), was skipped for another reason (yellow),
    or failed (red).

    Args:
        reg: The planned registration, carrying node name, spec, and reason.
        outcome: One of ``"ok"``, ``"dryrun"``, ``"skip"``, or an error string.

    Returns:
        A Rich markup string for use as a tree leaf label.
    """
    if outcome == "ok":
        return f"[green]✓ registered on {reg.node_name} at {reg.host_path}[/]"
    if outcome == "dryrun":
        return f"[cyan]→ would register on {reg.node_name} at {reg.host_path}[/]"
    if reg.action == "skip" and reg.reason == ALREADY_REGISTERED_REASON:
        return f"[dim]• already registered on {reg.node_name}[/]"
    if reg.action == "skip":
        return f"[yellow]- skipped on {reg.node_name}: {reg.reason}[/]"
    return f"[red]✗ failed on {reg.node_name}: {outcome}[/]"


def render_registration_results(
    results: list[tuple[Registration, str]],
) -> None:
    """Print a per-volume tree showing each node's registration outcome.

    Results are grouped by volume name (first-seen order). Each volume becomes
    a bold tree root with one leaf per node. Dry-run results use "would register"
    leaves; real outcomes use success/dim/skip/error styling. The outcome strings
    already encode dry-run state (``"dryrun"``), so no separate flag is needed.

    Args:
        results: Pairs of (Registration, outcome) where outcome is ``"ok"``,
            ``"dryrun"``, ``"skip"``, or an error string.
    """
    # Group by volume name preserving first-seen order.
    groups: dict[str, list[tuple[Registration, str]]] = {}
    for reg, outcome in results:
        groups.setdefault(reg.spec.name, []).append((reg, outcome))

    trees: list[Tree] = []
    for name, items in groups.items():
        tree = Tree(f"[bold]{name}[/]")
        for reg, outcome in items:
            tree.add(_registration_leaf(reg, outcome))
        trees.append(tree)

    # A dry-run never actually registers, so the title must not claim it did.
    verb = "Would register" if any(outcome == "dryrun" for _, outcome in results) else "Registered"
    count = len(groups)
    _print_volume_groups(f"{verb} {count} volume{'s' if count != 1 else ''}", trees)


def _deletion_leaf(vol: HostVolumeListStub, outcome: str, node_names: dict[str, str]) -> str:
    """Return Rich markup for a single deletion result leaf.

    Args:
        vol: The registered host volume being deleted.
        outcome: One of ``"deleted"``, ``"would-delete"``, or an error string.
        node_names: Map of node_id to display name; unknown ids fall back to
            the first 8 characters of the id.

    Returns:
        A Rich markup string for use as a tree leaf label.
    """
    name = node_names.get(vol.node_id, vol.node_id[:8])
    if outcome == "deleted":
        return f"[green]✓ deleted on {name}[/]"
    if outcome == "would-delete":
        return f"[cyan]→ would delete on {name}[/]"
    return f"[red]✗ failed on {name}: {outcome}[/]"


def render_deletion_results(
    results: list[tuple[HostVolumeListStub, str]],
    *,
    node_names: dict[str, str],
) -> None:
    """Print a per-volume tree showing each node's deletion outcome.

    Results are grouped by volume name (first-seen order). Each volume becomes
    a bold tree root with one leaf per registered instance. The outcome strings
    already encode dry-run state (``"would-delete"``), so no separate flag is needed.

    Args:
        results: Pairs of (HostVolumeListStub, outcome) where outcome is
            ``"deleted"``, ``"would-delete"``, or an error string.
        node_names: Map of node_id to display name for building human-readable leaves.
    """
    # Group by volume name preserving first-seen order.
    groups: dict[str, list[tuple[HostVolumeListStub, str]]] = {}
    for vol, outcome in results:
        groups.setdefault(vol.name, []).append((vol, outcome))

    trees: list[Tree] = []
    for name, items in groups.items():
        tree = Tree(f"[bold]{name}[/]")
        for vol, outcome in items:
            tree.add(_deletion_leaf(vol, outcome, node_names))
        trees.append(tree)

    # A dry-run never actually deletes, so the title must not claim it did.
    verb = "Would delete" if any(outcome == "would-delete" for _, outcome in results) else "Deleted"
    count = len(groups)
    _print_volume_groups(f"{verb} {count} volume{'s' if count != 1 else ''}", trees)
