"""Shared interactive prompt helpers wrapping nclutils.ask.

Each selector runs the blocking questionary widget on a worker thread so it does
not block the event loop, then erases the residual answer line so it does not
leak into subsequent Rich output. Both selectors refuse to run off a terminal, so
no caller can mistake an unanswerable prompt for a decision the user made.
"""

from __future__ import annotations

import asyncio
import sys
from typing import cast

from nclutils import pp
from nclutils.ask import choose_multiple_from_list, choose_one_from_list


def is_interactive() -> bool:
    """Return True when the console is a real terminal, so prompts are usable.

    A single home for the terminal check so prompt-gating callers agree with the
    residual-line clearing below on what "interactive" means.
    """
    return pp.console().is_terminal


def can_prompt() -> bool:
    """Return True when a prompt can both render and read keystrokes.

    ``is_interactive`` describes stdout only. A questionary widget also reads keys, so a
    piped stdin makes prompting impossible even when the console is a terminal.
    """
    return is_interactive() and sys.stdin.isatty()


class PromptUnavailableError(Exception):
    """Raised when a choice needs a prompt the session cannot show."""


def require_prompt(*, needed: bool = True, what: str, remedy: str) -> None:
    """Fail fast when a choice needs a prompt this session cannot show.

    Off a terminal a questionary widget renders into the pipe and answers None, which
    reads as "nothing selected" or "declined" to every caller. Without this gate a
    scripted ``nd stop web`` reports an abort and still exits 0, so the script believes
    the job stopped. ``needed`` only means a prompt would otherwise be shown, not that
    the candidates are ambiguous, so the message says a choice is required rather than
    claiming ambiguity. ``remedy`` names the one thing that resolves this specific call
    site, since the call sites do not share a fix.
    """
    if needed and not can_prompt():
        msg = f"{what} requires an interactive terminal; {remedy}"
        raise PromptUnavailableError(msg)


def clear_prompt_line(lines: int = 1) -> None:
    """Erase the residual questionary answer line(s) on an interactive terminal.

    A no-op off a terminal (pipes, tests) so control codes never leak into output.
    """
    if not is_interactive():
        return
    console = pp.console()
    console.file.write(f"\x1b[{lines}A\x1b[J")
    console.file.flush()


_DEFAULT_PROMPT_REMEDY = "run in an interactive terminal"
# Remedies the commands report when a prompt they need cannot be shown
FORCE_REMEDY = "pass --force"
NAME_JOB_REMEDY = "name a job explicitly"


async def select_one[T](
    choices: list[tuple[str, T]], message: str, *, remedy: str = _DEFAULT_PROMPT_REMEDY
) -> T | None:
    """Prompt for a single choice, returning the value or None when cancelled.

    Args:
        choices: ``(label, value)`` pairs to offer.
        message: The question shown above the choices.
        remedy: What the user can do instead when the session cannot show the prompt,
            such as naming the flag that makes the choice unnecessary.

    Returns:
        T | None: The chosen value, or None when the user cancels.
    """
    require_prompt(what=f"'{message}'", remedy=remedy)
    chosen = cast(
        "T | None",
        await asyncio.to_thread(choose_one_from_list, choices, message),
    )
    clear_prompt_line()
    return chosen


async def select_many[T](
    choices: list[tuple[str, T]], message: str, *, remedy: str = _DEFAULT_PROMPT_REMEDY
) -> list[T] | None:
    """Prompt for multiple choices, returning the values or None when cancelled.

    Args:
        choices: ``(label, value)`` pairs to offer.
        message: The question shown above the choices.
        remedy: What the user can do instead when the session cannot show the prompt,
            such as naming the argument that makes the choice unambiguous.

    Returns:
        list[T] | None: The chosen values, or None when the user cancels.
    """
    require_prompt(what=f"'{message}'", remedy=remedy)
    chosen = cast(
        "list[T] | None",
        await asyncio.to_thread(choose_multiple_from_list, choices, message),
    )
    clear_prompt_line()
    return chosen


async def confirm(question: str, *, remedy: str) -> bool:
    """Ask a Yes/No question before an action the user may want to back out of.

    A cancelled prompt counts as No, so a caller never proceeds without an explicit Yes.

    Args:
        question: The question to show, phrased so Yes proceeds.
        remedy: The flag or step that skips this confirmation, reported when the
            session cannot show the prompt.

    Returns:
        bool: True when the user answers Yes.
    """
    require_prompt(what="Confirmation", remedy=remedy)
    answer = await select_one([("Yes", True), ("No", False)], question)
    return bool(answer)
