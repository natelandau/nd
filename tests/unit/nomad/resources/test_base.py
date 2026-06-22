"""Tests for the base resource decode helpers."""

import httpx2
import msgspec
import pytest

from nd.nomad.errors import NomadDecodeError
from nd.nomad.resources.base import BaseResource


class _Item(msgspec.Struct, frozen=True, kw_only=True):
    name: str


def _resource() -> BaseResource:
    return BaseResource(transport=None)  # type: ignore[arg-type]


def test_decode_returns_typed_object():
    """Verify that _decode parses a JSON object into the requested Struct type."""
    # Given
    resp = httpx2.Response(200, json={"name": "x"})

    # When
    item = _resource()._decode(resp, _Item)

    # Then
    assert item.name == "x"


def test_decode_list_returns_typed_list():
    """Verify that _decode_list parses a JSON array into a list of the requested Struct type."""
    # Given
    resp = httpx2.Response(200, json=[{"name": "a"}, {"name": "b"}])

    # When
    items = _resource()._decode_list(resp, _Item)

    # Then
    assert [i.name for i in items] == ["a", "b"]


def test_decode_raises_nomad_decode_error_on_mismatch():
    """Verify that _decode raises NomadDecodeError when the JSON does not match the schema."""
    # Given
    resp = httpx2.Response(200, json={"name": 123})

    # When / Then
    with pytest.raises(NomadDecodeError):
        _resource()._decode(resp, _Item)


def test_decode_list_raises_nomad_decode_error_on_mismatch():
    """Verify that _decode_list raises NomadDecodeError when a list element violates the schema."""
    # Given: a JSON array whose element has the wrong type for the 'name' field
    resp = httpx2.Response(200, json=[{"name": 123}])

    # When / Then
    with pytest.raises(NomadDecodeError):
        _resource()._decode_list(resp, _Item)
