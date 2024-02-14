"""Nomad client (node) classes and functions."""

import rich.repr


@rich.repr.auto
class Node:
    """Represents a Nomad client (node)."""

    def __init__(  # noqa: PLR0917
        self,
        address: str = "",
        datacenter: str = "",
        eligible: str = "",
        id_num: str = "",
        name: str = "",
        node_class: str = "",
        status: str = "",
        version: str = "",
    ) -> None:
        self.name = name
        self.id_num = id_num
        self.id_short = id_num.split("-")[0]
        self.address = address
        self.status = status
        self.eligible = eligible
        self.datacenter = datacenter
        self.node_class = node_class
        self.version = version
