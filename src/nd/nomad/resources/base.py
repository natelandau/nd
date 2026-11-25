"""Shared base class for Nomad API resource namespaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nd.nomad.models import decode_json

if TYPE_CHECKING:
    from typing import Any

    import httpx2

    from nd.nomad.transport import AsyncTransport


class BaseResource:
    """Base class holding a transport reference and msgspec decode helpers."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    def _decode[T](self, response: httpx2.Response, type_: type[T]) -> T:
        """Decode a response body into ``type_``, mapping failures to NomadDecodeError."""
        return decode_json(data=response.content, type_=type_)

    def _decode_list[T](self, response: httpx2.Response, item_type: type[T]) -> list[T]:
        """Decode a JSON array into ``list[item_type]``."""
        return self._decode(response=response, type_=list[item_type])  # ty: ignore[invalid-type-form]

    async def _paginate_list[T](
        self, path: str, item_type: type[T], *, params: dict[str, Any] | None = None
    ) -> list[T]:
        """Fetch every page of a list endpoint, decoding each into ``item_type``."""
        items: list[T] = []
        async for response in self._transport.paginate(path, params=params):
            items.extend(self._decode_list(response=response, item_type=item_type))
        return items
