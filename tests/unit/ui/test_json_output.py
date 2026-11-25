"""Tests for the JSON document writer."""

from __future__ import annotations

import json

import msgspec
import pytest

from nd.ui.json_output import print_json


class _Sample(msgspec.Struct, frozen=True, kw_only=True):
    name: str


@pytest.mark.parametrize(
    "value",
    [
        pytest.param('we"b\\x', id="quotes"),
        pytest.param("café-日本", id="unicode"),
        pytest.param("x" * 500, id="long"),
    ],
)
def test_print_json_writes_one_unwrapped_line(
    value: str, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    """Verify any string value round-trips as one JSON line, never wrapped at terminal width."""
    # Given a document holding an awkward value
    document = _Sample(name=value)

    # When printing it
    print_json(document)

    # Then stdout is exactly one line of valid JSON carrying the value
    out = capsysbinary.readouterr().out
    assert out.endswith(b"\n")
    assert out.count(b"\n") == 1
    assert json.loads(out) == {"name": value}
