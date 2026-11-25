"""Tests for the JSON document writer."""

from __future__ import annotations

import contextlib
import io
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


def test_print_json_writes_to_text_only_stdout() -> None:
    """Verify a stdout without a byte buffer, such as a redirected StringIO, still gets the JSON."""
    # Given stdout redirected to a text-only stream
    stream = io.StringIO()

    # When printing a document
    with contextlib.redirect_stdout(stream):
        print_json(_Sample(name="web"))

    # Then the stream holds the JSON line
    assert stream.getvalue() == '{"name":"web"}\n'
