"""Shared scaffolding for the job-lifecycle commands (``run``, ``stop``, ``update``).

These commands share the same shape: resolve node names once, optionally confirm,
run every target under one live panel, then emit durable lines for the outcomes that
did not finish cleanly and compute an exit code. Every command reports through the
one ``Outcome`` type here, so the finished row, report line, final title, and exit
code all derive from it the same way.
"""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from nclutils import pp

from nd.binary import NomadBinaryError
from nd.nomad.errors import NomadError
from nd.ui.duration import summary_title
from nd.ui.live_panel import run_rows
from nd.ui.prompts import confirm
from nd.ui.styles import OUTCOME_GLYPH

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from nd.ui.live_panel import PanelUpdate


class Severity(enum.StrEnum):
    """How cleanly one target's work finished, which sets its glyph, color, and exit code."""

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


_SEVERITY_COLOR: dict[Severity, str] = {
    Severity.OK: "green",
    Severity.WARN: "yellow",
    Severity.FAIL: "red",
}


@dataclass(frozen=True, kw_only=True)
class Outcome:
    """The terminal result of one target's work in a lifecycle command.

    Attributes:
        name: The job name shown on the row and in report lines.
        severity: Whether the work succeeded, needs attention, or failed.
        label: The command's status word for the finished row, e.g. ``still draining``.
        detail: Why the work did not finish cleanly, for the report line.
        warnings: Warnings Nomad returned on register, surfaced after the panel closes.
    """

    name: str
    severity: Severity
    label: str
    detail: str = ""
    warnings: str = ""

    def row(self) -> tuple[str, str]:
        """Build the finished row's ``(glyph, label)``, both colored by severity.

        Returns:
            tuple[str, str]: The glyph and the colored status label.
        """
        # The label carries its glyph's color so the status word reads on its own.
        color = _SEVERITY_COLOR[self.severity]
        return (OUTCOME_GLYPH[self.severity], f"[{color}]{self.label}[/]")


async def confirm_jobs(names: Sequence[str], *, verb: str, remedy: str) -> bool:
    """Prompt the user to confirm a job action, returning True to proceed.

    ``verb`` is the leading phrase (e.g. ``"Stop and PURGE"``); the shared wording
    keeps the confirmation prompt identical across the commands that use it.
    ``remedy`` names the flag that skips this command's confirmation, reported when
    the session cannot show the prompt.
    """
    return await confirm(f"{verb} {len(names)} job(s): {', '.join(names)}?", remedy=remedy)


def final_panel_title(outcomes: list[Outcome], seconds: float, *, verb: str) -> str:
    """Build the live panel's final title from the ordered outcomes and elapsed time.

    Counts the clean outcomes so the title reads ``Deployed 2 jobs`` or the ``1 of 2
    jobs`` partial form. ``verb`` is the past-tense summary word each command supplies.
    """
    ok = sum(1 for o in outcomes if o.severity is Severity.OK)
    return summary_title(verb, done=ok, total=len(outcomes), seconds=seconds)


def exit_code_for(outcomes: list[Outcome]) -> int:
    """Return 0 only when every target finished cleanly, otherwise 1."""
    return 0 if all(o.severity is Severity.OK for o in outcomes) else 1


def report_outcomes(outcomes: list[Outcome], *, fail_verb: str) -> None:
    """Emit a durable log line for every outcome that did not finish cleanly.

    The live panel is transient on a pipe or in CI, so each timed-out or failed
    outcome is echoed here: a warning reading the detail (or the row label when there
    is none) and an error reading ``<name> failed to <fail_verb>``. Any register
    warnings follow as their own line.
    """
    for outcome in outcomes:
        if outcome.severity is Severity.WARN:
            pp.warning(f"{outcome.name}: {outcome.detail or outcome.label}")
        elif outcome.severity is Severity.FAIL:
            pp.error(
                f"{outcome.name} failed to {fail_verb}",
                details=[outcome.detail] if outcome.detail else None,
            )
        if outcome.warnings:
            pp.warning(f"{outcome.name}: {outcome.warnings}")


async def run_outcome_rows[I](
    items: list[I],
    work: Callable[[I, PanelUpdate], Awaitable[Outcome]],
    *,
    label_of: Callable[[I], str],
    initial_phase: str,
    running_title: str,
    done_verb: str,
    fail_verb: str,
) -> int:
    """Run every target under one live panel, report what went wrong, and return the exit code.

    Use it as the whole watched phase of a lifecycle command: the finished rows and the
    final title come from each ``Outcome``, and the panel is followed by durable lines
    for anything that did not finish cleanly.

    Args:
        items: The targets to work on concurrently.
        work: Async callable receiving ``(item, update)`` and returning its outcome.
        label_of: Each target's row label.
        initial_phase: Phase text shown on every row before ``work`` updates it.
        running_title: Panel title while work is in progress.
        done_verb: Past-tense verb for the final title, e.g. ``Deployed``.
        fail_verb: Verb for the ``<name> failed to <verb>`` error line.

    Returns:
        int: 0 when every target finished cleanly, otherwise 1.
    """
    ordered = await run_rows(
        items,
        work,
        label_of=label_of,
        initial_phase=initial_phase,
        finish_of=Outcome.row,
        running_title=running_title,
        final_title=partial(final_panel_title, verb=done_verb),
    )
    report_outcomes(ordered, fail_verb=fail_verb)
    return exit_code_for(ordered)


async def request_all[I](
    items: list[I],
    request: Callable[[I], Awaitable[str]],
    *,
    name_of: Callable[[I], str],
    summary_of: Callable[[int], str],
    fail_verb: str,
) -> int:
    """Send one request per target concurrently and report the results without watching.

    Use it for a ``--detach`` mode: a failure on one target is reported and does not
    stop the others. One success line names every accepted target, then each failure
    (and any warnings the request returned) follows in target order.

    Args:
        items: The targets to send a request for.
        request: Async callable that sends one target's request and returns any
            warnings Nomad attached, or an empty string. Raises on failure.
        name_of: Each target's name for the report lines.
        summary_of: The success line for a count of accepted targets.
        fail_verb: Verb for the ``<name> failed to <verb>`` error line.

    Returns:
        int: 0 when every request was accepted, otherwise 1.
    """

    async def attempt(item: I) -> tuple[str, str | None]:
        try:
            return (await request(item), None)
        except (NomadBinaryError, NomadError) as exc:
            return ("", str(exc))

    results = await asyncio.gather(*(attempt(item) for item in items))
    accepted = [
        name_of(item) for item, (_, error) in zip(items, results, strict=True) if error is None
    ]
    if accepted:
        pp.success(summary_of(len(accepted)), details=accepted)
    for item, (warnings, error) in zip(items, results, strict=True):
        if error is not None:
            pp.error(f"{name_of(item)} failed to {fail_verb}", details=[error])
        elif warnings:
            pp.warning(f"{name_of(item)}: {warnings}")
    return 0 if len(accepted) == len(items) else 1
