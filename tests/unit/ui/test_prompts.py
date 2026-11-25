"""Tests for shared interactive prompt wrappers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nd.ui import prompts


def test_select_one_returns_choice(monkeypatch) -> None:
    """Verify select_one returns the chosen value and clears the prompt line."""
    # Given a stubbed single-choice widget and a recorded clear call
    cleared: list[int] = []
    monkeypatch.setattr(prompts, "can_prompt", lambda: True)
    monkeypatch.setattr(prompts, "clear_prompt_line", lambda lines=1: cleared.append(lines))
    monkeypatch.setattr(prompts, "choose_one_from_list", lambda choices, message: choices[0][1])
    # When
    result = asyncio.run(prompts.select_one([("a", 1), ("b", 2)], "pick"))
    # Then
    assert result == 1
    assert cleared == [1]


def test_select_many_returns_choices(monkeypatch) -> None:
    """Verify select_many returns the chosen list and clears the prompt line."""
    monkeypatch.setattr(prompts, "can_prompt", lambda: True)
    monkeypatch.setattr(prompts, "clear_prompt_line", lambda lines=1: None)
    monkeypatch.setattr(
        prompts, "choose_multiple_from_list", lambda choices, message: [choices[0][1]]
    )
    result = asyncio.run(prompts.select_many([("a", 1), ("b", 2)], "pick"))
    assert result == [1]


@pytest.mark.parametrize(
    ("selector", "widget"),
    [
        (prompts.select_one, "choose_one_from_list"),
        (prompts.select_many, "choose_multiple_from_list"),
    ],
)
@pytest.mark.parametrize(
    ("remedy_kwargs", "expected_remedy"),
    [
        ({}, "run in an interactive terminal"),
        ({"remedy": "name a job explicitly"}, "name a job explicitly"),
    ],
)
def test_selector_off_a_terminal_raises_with_remedy(
    monkeypatch, selector, widget, remedy_kwargs, expected_remedy
) -> None:
    """Verify a selector refuses to render into a pipe and names the caller's remedy."""
    # Given a session that cannot show a prompt and a widget that must not be reached
    monkeypatch.setattr(prompts, "can_prompt", lambda: False)
    monkeypatch.setattr(
        prompts, widget, lambda choices, message: pytest.fail("the widget must not run")
    )

    # When selecting, Then it is a hard error naming the remedy
    with pytest.raises(prompts.PromptUnavailableError) as exc:
        asyncio.run(selector([("a", 1)], "pick", **remedy_kwargs))
    assert str(exc.value) == f"'pick' requires an interactive terminal; {expected_remedy}"


@pytest.mark.parametrize(("answer", "expected"), [(True, True), (False, False), (None, False)])
def test_confirm_proceeds_only_on_yes(monkeypatch, answer, expected) -> None:
    """Verify confirm returns True only for Yes, treating a cancelled prompt as No."""
    # Given a Yes/No widget that answers with the parametrized value
    monkeypatch.setattr(prompts, "can_prompt", lambda: True)
    monkeypatch.setattr(prompts, "clear_prompt_line", lambda lines=1: None)
    monkeypatch.setattr(prompts, "choose_one_from_list", lambda choices, message: answer)

    # When confirming
    result = asyncio.run(prompts.confirm("Delete it?", remedy="pass --force"))

    # Then only an explicit Yes proceeds
    assert result is expected


def test_confirm_off_a_terminal_raises(monkeypatch) -> None:
    """Verify an unanswerable confirmation is a hard error naming the skip flag."""
    # Given a session that cannot show a prompt
    monkeypatch.setattr(prompts, "can_prompt", lambda: False)

    # When confirming, Then it refuses rather than reading no answer as "no"
    with pytest.raises(prompts.PromptUnavailableError) as exc:
        asyncio.run(prompts.confirm("Delete it?", remedy="pass --force"))
    assert str(exc.value) == "Confirmation requires an interactive terminal; pass --force"


def test_require_prompt_not_needed_is_a_noop(monkeypatch) -> None:
    """Verify an unambiguous choice needs no terminal."""
    # Given a session that cannot show a prompt
    monkeypatch.setattr(prompts, "can_prompt", lambda: False)

    # When no prompt would be shown anyway, Then nothing is raised
    prompts.require_prompt(needed=False, what="Job selection", remedy="name the job")


def test_require_prompt_message_names_the_remedy(monkeypatch) -> None:
    """Verify the error tells the user the one flag that resolves their call site."""
    # Given a session that cannot show a prompt
    monkeypatch.setattr(prompts, "can_prompt", lambda: False)

    # When a prompt is needed, Then the message carries both the subject and the remedy
    with pytest.raises(prompts.PromptUnavailableError) as exc:
        prompts.require_prompt(what="Confirmation", remedy="pass --force")
    assert str(exc.value) == "Confirmation requires an interactive terminal; pass --force"


def test_can_prompt_requires_a_terminal_on_both_streams(monkeypatch) -> None:
    """Verify can_prompt is False when stdin is piped even though stdout is a terminal."""
    # Given a terminal console but a piped stdin
    monkeypatch.setattr(prompts, "is_interactive", lambda: True)
    monkeypatch.setattr(prompts.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    # When asking whether a prompt is possible, Then it is not
    assert prompts.can_prompt() is False


def test_can_prompt_true_when_both_streams_are_terminals(monkeypatch) -> None:
    """Verify can_prompt is True only when the console and stdin are both terminals."""
    # Given a terminal console and a terminal stdin
    monkeypatch.setattr(prompts, "is_interactive", lambda: True)
    monkeypatch.setattr(prompts.sys, "stdin", SimpleNamespace(isatty=lambda: True))

    # When asking whether a prompt is possible, Then it is
    assert prompts.can_prompt() is True
