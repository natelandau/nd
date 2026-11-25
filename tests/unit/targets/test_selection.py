"""Tests for generic target matching."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
import typer

from nd.targets import selection
from nd.targets.selection import (
    TargetResolution,
    pick_single,
    resolve_targets,
    select_one_candidate,
    select_targets,
)


@dataclass(frozen=True)
class _Named:
    name: str


def _items() -> list[_Named]:
    return [_Named("web"), _Named("worker"), _Named("db")]


@pytest.mark.parametrize(
    ("name_arg", "expected_names", "needs_prompt"),
    [
        pytest.param(None, ["web", "worker", "db"], True, id="no-argument"),
        pytest.param("db", ["db"], False, id="single-match"),
        pytest.param("w", ["web", "worker"], True, id="several-matches"),
        pytest.param("W", ["web", "worker"], True, id="case-insensitive"),
        pytest.param("or", ["worker"], False, id="mid-string"),
        pytest.param("zzz", [], False, id="no-match"),
    ],
)
def test_resolve_targets_matches_substring(
    *, name_arg: str | None, expected_names: list[str], needs_prompt: bool
) -> None:
    """Verify a case-insensitive substring match, prompting only when the choice is ambiguous."""
    # Given items named web, worker, and db
    items = _items()

    # When resolving with the parametrized argument
    res = resolve_targets(items, name_arg, name_of=lambda i: i.name)

    # Then the matching items are candidates, prompting when no argument or several match
    assert [i.name for i in res.candidates] == expected_names
    assert res.needs_prompt is needs_prompt


def test_select_one_candidate_unambiguous_returns_lone_item() -> None:
    """Verify an unambiguous resolution returns its single candidate without prompting."""
    # Given a resolution that matched exactly one item and needs no prompt
    resolution = TargetResolution(candidates=["web"], needs_prompt=False)

    # When selecting a single candidate
    result = asyncio.run(select_one_candidate(resolution, "Pick", label_of=str))

    # Then the lone candidate is returned
    assert result == "web"


def test_select_one_candidate_empty_returns_none() -> None:
    """Verify a resolution with no candidates returns None (caller reports the miss)."""
    # Given a resolution that matched nothing
    resolution = TargetResolution(candidates=[], needs_prompt=False)

    # When selecting a single candidate
    result = asyncio.run(select_one_candidate(resolution, "Pick", label_of=str))

    # Then None is returned
    assert result is None


def test_pick_single_one_item_returns_it() -> None:
    """Verify a single item is returned without a prompt."""
    # Given exactly one item
    items = ["only"]

    # When picking a single item
    result = asyncio.run(pick_single(items, "Pick", label_of=str))

    # Then it is returned directly
    assert result == "only"


def test_pick_single_empty_returns_none() -> None:
    """Verify an empty list returns None."""
    # Given no items
    items: list[str] = []

    # When picking a single item
    result = asyncio.run(pick_single(items, "Pick", label_of=str))

    # Then None is returned
    assert result is None


def _select(name_arg: str | None) -> list[_Named]:
    return asyncio.run(
        select_targets(
            _items(),
            name_arg,
            name_of=lambda i: i.name,
            prompt="Select items",
            miss_noun="item",
            remedy="name an item explicitly",
        )
    )


def test_select_targets_returns_lone_match_without_prompt() -> None:
    """Verify a name matching one item selects it without prompting."""
    # Given/When selecting by a name that matches only "db"
    result = _select("db")

    # Then that item is returned
    assert result == [_Named("db")]


def test_select_targets_returns_prompted_choices(monkeypatch) -> None:
    """Verify an ambiguous name returns what the user picks in the multi-select."""

    # Given a multi-select that picks the first offered item
    async def pick_first(choices, message, *, remedy):  # noqa: ANN202
        return [choices[0][1]]

    monkeypatch.setattr(selection, "select_many", pick_first)

    # When selecting by a name that matches "web" and "worker"
    result = _select("w")

    # Then only the picked item is returned
    assert result == [_Named("web")]


@pytest.mark.parametrize(
    ("name_arg", "picked", "expected_code"),
    [
        pytest.param("w", [], 0, id="nothing-selected"),
        pytest.param("w", None, 0, id="prompt-cancelled"),
        pytest.param("zzz", None, 1, id="no-match"),
    ],
)
def test_select_targets_exits_without_a_selection(
    monkeypatch, name_arg, picked, expected_code
) -> None:
    """Verify an empty selection exits 0 and an unmatched name exits 1."""

    # Given a multi-select that returns the parametrized answer
    async def answer(choices, message, *, remedy):  # noqa: ANN202
        return picked

    monkeypatch.setattr(selection, "select_many", answer)

    # When selecting, Then the command ends with the expected code
    with pytest.raises(typer.Exit) as exc:
        _select(name_arg)
    assert exc.value.exit_code == expected_code
