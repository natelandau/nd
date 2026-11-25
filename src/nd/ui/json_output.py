"""Write a command's result as one JSON document on stdout for scripts and agents."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import msgspec

if TYPE_CHECKING:
    from collections.abc import Sequence


def print_json(document: msgspec.Struct | Sequence[msgspec.Struct]) -> None:
    """Print a document as compact JSON so `jq` and agents can parse a command's result.

    Bypasses Rich so the output is never wrapped at terminal width, highlighted, or
    interpreted as markup.

    Args:
        document: The struct, or list of structs, to encode.
    """
    encoded = msgspec.json.encode(document) + b"\n"
    # A redirected stdout (StringIO, an IDE console) can be text-only, with no byte buffer.
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(encoded.decode())
        sys.stdout.flush()
        return
    buffer.write(encoded)
    buffer.flush()
