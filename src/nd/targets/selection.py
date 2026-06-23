"""Generic target matching for commands that accept a name/prefix argument."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nclutils import pp

from nd.ui.prompts import select_many, select_one

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class TargetResolution[T]:
    """The result of matching an optional name argument against candidate items."""

    candidates: list[T] = field(default_factory=list)
    needs_prompt: bool = False


def resolve_targets[T](
    items: list[T], arg: str | None, *, name_of: Callable[[T], str]
) -> TargetResolution[T]:
    """Decide which items a name/prefix argument targets.

    With no argument every item is offered for a multi-select. With an argument,
    items whose name starts with it (case-insensitive) are matched: a single match
    is auto-selected, several matches are offered for a prompt, and no match yields
    no candidates.
    """
    if arg is None:
        return TargetResolution(candidates=list(items), needs_prompt=True)
    needle = arg.lower()
    matches = [item for item in items if name_of(item).lower().startswith(needle)]
    if len(matches) <= 1:
        return TargetResolution(candidates=matches, needs_prompt=False)
    return TargetResolution(candidates=matches, needs_prompt=True)


async def select_candidates[T](
    resolution: TargetResolution[T], prompt: str, *, label_of: Callable[[T], str]
) -> list[T] | None:
    """Resolve a selection, prompting with ``prompt`` when several items match.

    Shared by the commands so selection UX stays identical: ``label_of`` renders
    each item's prompt line. Returns None when the user cancels or selects nothing
    (caller exits 0). An empty list means an argument matched no items (caller
    reports and exits 1).
    """
    if not resolution.needs_prompt:
        return resolution.candidates
    choices = [(label_of(item), item) for item in resolution.candidates]
    chosen = await select_many(choices, prompt)
    if not chosen:
        pp.info("Nothing selected")
        return None
    return chosen


async def select_one_candidate[T](
    resolution: TargetResolution[T], prompt: str, *, label_of: Callable[[T], str]
) -> T | None:
    """Resolve a single selection from a name-argument resolution.

    The single-select sibling of ``select_candidates``: an unambiguous resolution
    returns its lone candidate directly, while several matches are offered with
    ``select_one``. Returns None when nothing matched (caller reports the miss) or
    the user cancels.
    """
    if not resolution.needs_prompt:
        return resolution.candidates[0] if resolution.candidates else None
    choices = [(label_of(item), item) for item in resolution.candidates]
    return await select_one(choices, prompt)


async def pick_single[T](items: list[T], prompt: str, *, label_of: Callable[[T], str]) -> T | None:
    """Auto-select a lone item, or prompt with ``select_one`` when several exist.

    Used by the allocation and task steps, which take no name argument: one item is
    returned without a prompt, more than one is offered for a single choice. Returns
    None for an empty list or when the user cancels.
    """
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    choices = [(label_of(item), item) for item in items]
    return await select_one(choices, prompt)
