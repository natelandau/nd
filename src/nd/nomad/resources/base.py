"""Shared base class for Nomad API resource namespaces."""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, TypeVar

import msgspec

from nd.nomad.errors import NomadDecodeError

if TYPE_CHECKING:
    import httpx2

    from nd.nomad.transport import AsyncTransport

T = TypeVar("T")


class BaseResource:
    """Base class holding a transport reference and msgspec decode helpers."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    def _decode(self, response: httpx2.Response, type_: type[T]) -> T:
        """Decode a response body into ``type_``, mapping failures to NomadDecodeError."""
        try:
            return msgspec.json.decode(response.content, type=type_)
        except msgspec.DecodeError as exc:
            msg = f"Failed to decode {type_.__name__}: {exc}"
            raise NomadDecodeError(msg, payload=response.text[:500]) from exc

    def _decode_list(self, response: httpx2.Response, item_type: type[T]) -> list[T]:
        """Decode a JSON array into ``list[item_type]``."""
        try:
            return msgspec.json.decode(response.content, type=builtins.list[item_type])  # ty: ignore[invalid-type-form]
        except msgspec.DecodeError as exc:
            msg = f"Failed to decode list[{item_type.__name__}]: {exc}"
            raise NomadDecodeError(msg, payload=response.text[:500]) from exc
