"""msgspec models for Nomad API responses."""

import msgspec

from nd.nomad.errors import NomadDecodeError

# Bytes of an undecodable body kept on the error for debugging
_ERROR_PAYLOAD_LIMIT = 500


class NomadModel(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """Base for Nomad API response models.

    Subclass to decode Nomad's PascalCase JSON into immutable structs. Subclasses
    inherit the renaming but must repeat ``frozen=True, kw_only=True``: msgspec does
    not inherit ``kw_only``, and type checkers reject a subclass that omits ``frozen``.
    """


def decode_json[T](data: bytes, type_: type[T]) -> T:
    """Decode Nomad JSON into ``type_`` so a shape problem surfaces as a Nomad error.

    Use this for any Nomad JSON, from the API or the ``nomad`` binary, so callers handle
    one error type and ``main()`` reports it cleanly.

    Args:
        data: The raw JSON bytes.
        type_: The type to decode into, such as a ``NomadModel`` subclass or ``list[...]``.

    Returns:
        T: The decoded value.

    Raises:
        NomadDecodeError: If the JSON is malformed or does not match ``type_``.
    """
    try:
        return msgspec.json.decode(data, type=type_)
    except msgspec.DecodeError as exc:
        # A generic alias such as list[Item] reports its origin's bare __name__ ("list")
        type_name = type_.__name__ if isinstance(type_, type) else repr(type_)
        msg = f"Failed to decode {type_name}: {exc}"
        payload = data[:_ERROR_PAYLOAD_LIMIT].decode("utf-8", "replace")
        raise NomadDecodeError(msg, payload=payload) from exc
