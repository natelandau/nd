"""Nomad client (node) classes and functions."""

import rich.repr

from nd._commands.utils import make_nomad_api_call
from nd._commands.utils.alerts import logger as log


@rich.repr.auto
class Node:
    """Class for a Nomad client node."""

    def __init__(
        self,
        name: str = "",
        id_num: str = "",
        address: str = "",
        status: str = "",
        eligible: str = "",
        datacenter: str = "",
        node_class: str = "",
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


def populate_nodes(nomad_api_url: str) -> list[Node]:
    """Create class 'Node' objects from the Nomad HTTP API.

    Args:
        nomad_api_url (str): The URL of the Nomad HTTP API.

    Returns:
        list[str]: Node Class objects
    """
    url = f"{nomad_api_url}/nodes"

    log.trace(f"Populating nodes from {url}")
    response = make_nomad_api_call(url, "GET")
    return [
        Node(
            node["Name"],
            node["ID"],
            node["Address"],
            node["Status"],
            node["SchedulingEligibility"],
            node["Datacenter"],
            node["NodeClass"],
            node["Version"],
        )
        for node in response
    ]
