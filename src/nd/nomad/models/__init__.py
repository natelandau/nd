"""msgspec models for Nomad API responses."""

import msgspec


class NomadModel(msgspec.Struct, rename="pascal", frozen=True, kw_only=True):
    """Base for Nomad API response models.

    Subclass to decode Nomad's PascalCase JSON into immutable structs. Subclasses
    inherit the renaming but must repeat ``frozen=True, kw_only=True``: msgspec does
    not inherit ``kw_only``, and type checkers reject a subclass that omits ``frozen``.
    """
