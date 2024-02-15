"""Interactive questions and prompts for the nd package."""
from typing import Any

import questionary
import typer

from nd.constants import NDObject
from nd.utils.alerts import logger as log

# Reset the default style of the questionary prompts qmark
questionary.prompts.checkbox.DEFAULT_STYLE = questionary.Style([("qmark", "")])
questionary.prompts.common.DEFAULT_STYLE = questionary.Style([("qmark", "")])
questionary.prompts.confirm.DEFAULT_STYLE = questionary.Style([("qmark", "")])
questionary.prompts.confirm.DEFAULT_STYLE = questionary.Style([("qmark", "")])
questionary.prompts.path.DEFAULT_STYLE = questionary.Style([("qmark", "")])
questionary.prompts.select.DEFAULT_STYLE = questionary.Style([("qmark", "")])
questionary.prompts.text.DEFAULT_STYLE = questionary.Style([("qmark", "")])

STYLE = questionary.Style(
    [
        ("qmark", "bold"),
        ("question", "bold"),
        ("separator", "fg:#808080"),
        ("answer", "fg:#FF9D00 bold"),
        ("instruction", "fg:#808080"),
        ("highlighted", "bold underline"),
        ("text", ""),
        ("pointer", "bold"),
    ]
)


def question_selection(
    choices: list[Any], question: str = "Select an option"
) -> Any:  # pragma: no cover
    """Ask the user to select an item from a list.

    Args:
        question (str, optional): The question to ask. Defaults to "Select an option".
        choices (list[Any]): The list of choices.

    Returns:
        any: The selected item value.
    """
    choices.insert(0, questionary.Separator())
    choices.extend((questionary.Separator(), {"name": "Abort", "value": "Abort"}))
    answer = questionary.select(
        question,
        choices=choices,
        use_shortcuts=False,
        style=STYLE,
        qmark="INPUT    |",
    ).ask()

    if answer is None or answer == "Abort":
        raise typer.Abort()

    return answer


def select_one(items: list, nd_object: NDObject, search_term: str | None = None) -> Any:
    """Select one item from a list of items.

    Args:
        items (list): list of items to select from
        nd_object (NDObject): NDObject type of items in the list
        search_term (str, optional): String to search for in item names. Defaults to None.

    Returns:
        Selected elected item
    """
    if len(items) == 1:
        return items[0]

    choices: list[Any] = []

    match nd_object:
        case NDObject.JOBFILE:
            description = "job file"
            choices.extend([{"name": i.name, "value": i} for i in items])
        case NDObject.RUNNING_JOB:
            description = "running job"
            choices.extend([{"name": i.name, "value": i} for i in items])
        case NDObject.TASK:
            description = "task"
            choices.extend([{"name": i.name, "value": i} for i in items])
        case _:
            description = "option"
            choices.extend([{"name": i.name, "value": i} for i in items])

    if len(items) == 0:
        log.error(
            f"No {description} found matching '{search_term}' Exiting."
            if search_term
            else f"No {description} found. Exiting."
        )
        raise typer.Exit(1)

    return question_selection(
        choices,
        f"Select a {description} matching term {search_term}"
        if search_term
        else f"Select a {description}",
    )
