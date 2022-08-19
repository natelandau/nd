"""Shared utility functions."""

from collections.abc import Generator
from typing import Any

from rich.prompt import Prompt

from nd._commands.utils.job_files import JobFile


def select_one(items: list) -> Any:
    """Select one item from a list of items."""
    if len(items) == 0:
        return None
    elif len(items) == 1:
        return items[0]
    else:

        choices = []
        for i in items:
            if type(i) == JobFile:
                choices.append(i.name)
            else:
                choices.append(i)

        choice = Prompt.ask("Enter item to select: ", choices=choices)
        return items[choices.index(choice)]


def chunks(lst: list, n: int) -> Generator[list, None, None]:
    """Yield successive n-sized chunks from lst.

    Args:
        lst (list): list to chunk
        n (int): chunk size

    Yields:
        list: list of n-sized chunks
    """
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
