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


def test_resolve_targets_no_arg_prompts_all() -> None:
    """Verify a missing argument offers every item for a prompt."""
    res = resolve_targets(_items(), None, name_of=lambda i: i.name)
    assert res.needs_prompt is True
    assert [i.name for i in res.candidates] == ["web", "worker", "db"]


def test_resolve_targets_single_match_auto() -> None:
    """Verify a substring that matches one item auto-selects without a prompt."""
    res = resolve_targets(_items(), "db", name_of=lambda i: i.name)
    assert res.needs_prompt is False
    assert [i.name for i in res.candidates] == ["db"]


def test_resolve_targets_multi_match_prompts() -> None:
    """Verify a substring matching several items requests a prompt."""
    res = resolve_targets(_items(), "w", name_of=lambda i: i.name)
    assert res.needs_prompt is True
    assert {i.name for i in res.candidates} == {"web", "worker"}


def test_resolve_targets_matches_mid_string_substring() -> None:
    """Verify a substring matches anywhere in the name, not just the prefix."""
    # Given items whose names share the interior fragment "or"
    items = [_Named("reverse-proxy"), _Named("worker"), _Named("db")]

    # When resolving with a fragment that appears mid-name
    res = resolve_targets(items, "or", name_of=lambda i: i.name)

    # Then only the item containing it matches, without a prompt
    assert res.needs_prompt is False
    assert [i.name for i in res.candidates] == ["worker"]


def test_resolve_targets_no_match() -> None:
    """Verify an unmatched substring yields no candidates and no prompt."""
    res = resolve_targets(_items(), "zzz", name_of=lambda i: i.name)
    assert res.needs_prompt is False
    assert res.candidates == []


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
