"""Tests for generic target matching."""

from __future__ import annotations

from dataclasses import dataclass

from nd.selection import resolve_targets


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
    """Verify a prefix that matches one item auto-selects without a prompt."""
    res = resolve_targets(_items(), "db", name_of=lambda i: i.name)
    assert res.needs_prompt is False
    assert [i.name for i in res.candidates] == ["db"]


def test_resolve_targets_multi_match_prompts() -> None:
    """Verify a prefix matching several items requests a prompt."""
    res = resolve_targets(_items(), "w", name_of=lambda i: i.name)
    assert res.needs_prompt is True
    assert {i.name for i in res.candidates} == {"web", "worker"}


def test_resolve_targets_no_match() -> None:
    """Verify an unmatched prefix yields no candidates and no prompt."""
    res = resolve_targets(_items(), "zzz", name_of=lambda i: i.name)
    assert res.needs_prompt is False
    assert res.candidates == []
