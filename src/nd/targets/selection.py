"""Generic target matching for commands that accept a name argument."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import typer
from nclutils import pp

from nd.ui.prompts import select_many, select_one

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True)
class TargetResolution[T]:
    """The result of matching an optional name argument against candidate items."""

    candidates: list[T] = field(default_factory=list)
    needs_prompt: bool = False


def resolve_targets[T](
    items: list[T], arg: str | None, *, name_of: Callable[[T], str]
) -> TargetResolution[T]:
    """Decide which items a name argument targets.

    With no argument every item is offered for a multi-select. With an argument,
    items whose name contains it (case-insensitive) are matched: a single match
    is auto-selected, several matches are offered for a prompt, and no match yields
    no candidates.
    """
    if arg is None:
        return TargetResolution(candidates=list(items), needs_prompt=True)
    needle = arg.lower()
    matches = [item for item in items if needle in name_of(item).lower()]
    if len(matches) <= 1:
        return TargetResolution(candidates=matches, needs_prompt=False)
    return TargetResolution(candidates=matches, needs_prompt=True)


async def select_candidates[T](
    resolution: TargetResolution[T], prompt: str, *, label_of: Callable[[T], str], remedy: str
) -> list[T] | None:
    """Resolve a selection, prompting with ``prompt`` when several items match.

    Shared by the commands so selection UX stays identical: ``label_of`` renders
    each item's prompt line. Returns None when the user cancels or selects nothing
    (caller exits 0). An empty list means an argument matched no items (caller
    reports and exits 1). ``remedy`` names the argument that makes this command's
    choice unambiguous, reported when the session cannot show the prompt.

    Raises:
        PromptUnavailableError: If a prompt is needed but the session cannot show one.
    """
    if not resolution.needs_prompt:
        return resolution.candidates
    choices = [(label_of(item), item) for item in resolution.candidates]
    chosen = await select_many(choices, prompt, remedy=remedy)
    if not chosen:
        pp.info("Nothing selected")
        return None
    return chosen


async def select_targets[T](
    items: list[T],
    name_arg: str | None,
    *,
    name_of: Callable[[T], str],
    label_of: Callable[[T], str] | None = None,
    prompt: str,
    miss_noun: str,
    remedy: str,
) -> list[T]:
    """Resolve a command's optional name argument to the items it acts on.

    Use it as the whole selection step of a command that takes an optional name
    substring: no name offers every item for a multi-select, a name auto-selects a
    lone match or prompts among several. The terminal cases end the command here so
    callers only ever see a real selection.

    Args:
        items: Every item the command could act on.
        name_arg: The name substring the user typed, or None to choose from all.
        name_of: The name that ``name_arg`` is matched against.
        label_of: Each item's prompt line. Defaults to ``name_of``.
        prompt: The multi-select question.
        miss_noun: What the items are, for the ``No <miss_noun> matching '<name>'`` error.
        remedy: What makes the choice unambiguous, reported when the session cannot
            show the prompt.

    Returns:
        list[T]: The selected items, never empty.

    Raises:
        typer.Exit: With code 0 when the user selects nothing, or code 1 after
            reporting that ``name_arg`` matched no item.
    """
    resolution = resolve_targets(items, name_arg, name_of=name_of)
    targets = await select_candidates(
        resolution, prompt, label_of=label_of or name_of, remedy=remedy
    )
    if targets is None:
        raise typer.Exit(0)
    if not targets:
        pp.error(f"No {miss_noun} matching '{name_arg}'")
        raise typer.Exit(1)
    return targets


def job_file_label(name: str, path: Path) -> str:
    """Label a job or volume for a prompt so same-named entries show their source file.

    Args:
        name: The job or volume name.
        path: The file that defines it.

    Returns:
        str: ``<name>  [<file name>]``.
    """
    return f"{name}  [{path.name}]"


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
