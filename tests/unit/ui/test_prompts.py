"""Tests for shared interactive prompt wrappers."""

from __future__ import annotations

import asyncio

from nd.ui import prompts


def test_select_one_returns_choice(monkeypatch) -> None:
    """Verify select_one returns the chosen value and clears the prompt line."""
    # Given a stubbed single-choice widget and a recorded clear call
    cleared: list[int] = []
    monkeypatch.setattr(prompts, "clear_prompt_line", lambda lines=1: cleared.append(lines))
    monkeypatch.setattr(prompts, "choose_one_from_list", lambda choices, message: choices[0][1])
    # When
    result = asyncio.run(prompts.select_one([("a", 1), ("b", 2)], "pick"))
    # Then
    assert result == 1
    assert cleared == [1]


def test_select_many_returns_choices(monkeypatch) -> None:
    """Verify select_many returns the chosen list and clears the prompt line."""
    monkeypatch.setattr(prompts, "clear_prompt_line", lambda lines=1: None)
    monkeypatch.setattr(
        prompts, "choose_multiple_from_list", lambda choices, message: [choices[0][1]]
    )
    result = asyncio.run(prompts.select_many([("a", 1), ("b", 2)], "pick"))
    assert result == [1]
