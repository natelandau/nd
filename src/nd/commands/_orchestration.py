"""Shared scaffolding for the job-lifecycle commands (``run``, ``stop``, ``update``).

These three commands share the same shape: resolve node names once, optionally
confirm, run every target under one live panel, then emit durable lines for the
outcomes that did not finish cleanly and compute an exit code. This module owns
that scaffolding so each command keeps only its own vocabulary (its status enum,
outcome type, and the labels it shows).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nclutils import pp

from nd.ui.duration import summary_title
from nd.ui.prompts import select_one
from nd.ui.styles import OUTCOME_GLYPH

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from nd.nomad import NomadClient


async def node_names_by_id(client: NomadClient) -> dict[str, str]:
    """Map node IDs to node names so a live panel's detail rows can show placement.

    Fetched once per command run and shared across every concurrent target, since
    the node roster does not change over the life of a single stop/run/update.
    """
    return {node.id: node.name for node in await client.nodes.list()}


async def confirm_jobs(names: Sequence[str], *, verb: str) -> bool:
    """Prompt the user to confirm a job action, returning True to proceed.

    ``verb`` is the leading phrase (e.g. ``"Stop and PURGE"``); the shared wording
    keeps the confirmation prompt identical across the commands that use it.
    """
    joined = ", ".join(names)
    answer = await select_one(
        [("Yes", True), ("No", False)],
        f"{verb} {len(names)} job(s): {joined}?",
    )
    return bool(answer)


def final_panel_title[O](
    outcomes: list[O], seconds: float, *, verb: str, succeeded: Callable[[O], bool]
) -> str:
    """Build the live panel's final title from the ordered outcomes and elapsed time.

    Counts the outcomes ``succeeded`` marks as clean so the title reads ``Deployed 2
    jobs`` or the ``1 of 2 jobs`` partial form. ``verb`` is the past-tense summary
    word each command supplies.
    """
    ok = sum(1 for o in outcomes if succeeded(o))
    return summary_title(verb, done=ok, total=len(outcomes), seconds=seconds)


def report_outcomes[O](  # noqa: PLR0913
    outcomes: list[O],
    *,
    name_of: Callable[[O], str],
    detail_of: Callable[[O], str],
    is_warn: Callable[[O], bool],
    is_fail: Callable[[O], bool],
    fail_verb: str,
    warn_fallback: str = "",
    warnings_of: Callable[[O], str] | None = None,
) -> None:
    """Emit a durable log line for every outcome that did not finish cleanly.

    The live panel is transient on a pipe or in CI, so each timed-out or failed
    outcome is echoed here: a warning for ``is_warn`` outcomes (falling back to
    ``warn_fallback`` when the outcome carries no detail) and an error reading
    ``<name> failed to <fail_verb>`` for ``is_fail`` outcomes. When ``warnings_of``
    is supplied, any non-empty register warning is surfaced as its own line.
    """
    for outcome in outcomes:
        if is_warn(outcome):
            pp.warning(f"{name_of(outcome)}: {detail_of(outcome) or warn_fallback}")
        elif is_fail(outcome):
            detail = detail_of(outcome)
            pp.error(
                f"{name_of(outcome)} failed to {fail_verb}",
                details=[detail] if detail else None,
            )
        if warnings_of is not None and (warnings := warnings_of(outcome)):
            pp.warning(f"{name_of(outcome)}: {warnings}")


def ok_row(label: str) -> tuple[str, str]:
    """Build a finished-row ``(glyph, label)`` for a clean success outcome."""
    return (OUTCOME_GLYPH["ok"], f"[green]{label}[/]")


def warn_row(label: str) -> tuple[str, str]:
    """Build a finished-row ``(glyph, label)`` for a warning outcome."""
    return (OUTCOME_GLYPH["warn"], f"[yellow]{label}[/]")


def fail_row(label: str) -> tuple[str, str]:
    """Build a finished-row ``(glyph, label)`` for a failure outcome."""
    return (OUTCOME_GLYPH["fail"], f"[red]{label}[/]")
