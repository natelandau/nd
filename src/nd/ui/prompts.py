"""Shared interactive prompt helpers wrapping nclutils.ask.

Each selector runs the blocking questionary widget on a worker thread so it does
not block the event loop, then erases the residual answer line so it does not
leak into subsequent Rich output.
"""

from __future__ import annotations

import asyncio
from typing import cast

from nclutils import pp
from nclutils.ask import choose_multiple_from_list, choose_one_from_list


def clear_prompt_line(lines: int = 1) -> None:
    """Erase the residual questionary answer line(s) on an interactive terminal.

    A no-op off a terminal (pipes, tests) so control codes never leak into output.
    """
    console = pp.console()
    if not console.is_terminal:
        return
    console.file.write(f"\x1b[{lines}A\x1b[J")
    console.file.flush()


async def select_one[T](choices: list[tuple[str, T]], message: str) -> T | None:
    """Prompt for a single choice, returning the value or None when cancelled."""
    chosen = cast(
        "T | None",
        await asyncio.to_thread(choose_one_from_list, choices, message),
    )
    clear_prompt_line()
    return chosen


async def select_many[T](choices: list[tuple[str, T]], message: str) -> list[T] | None:
    """Prompt for multiple choices, returning the values or None when cancelled."""
    chosen = cast(
        "list[T] | None",
        await asyncio.to_thread(choose_multiple_from_list, choices, message),
    )
    clear_prompt_line()
    return chosen
