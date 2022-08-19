"""Functions to work with the Nomad API."""
import sys

import requests

from nd._commands.utils.alerts import logger as log


def make_nomad_api_call(
    url: str,
    method: str,
    data: dict | None = None,
) -> dict:
    """Make a call to the Nomad HTTP API.

    Args:
        url (str): The URL to make the call to.
        method (str): The HTTP method to use.
        data (dict): The data to send with the request.

    Examples:
        nomad_api_call("/jobs")
        nomad_api_call("/jobs", {"prefix": "sonarr"})

    Returns:
        dict: The response from the Nomad API.

    Raises:
        exit: If the Nomad API is not available.
        exit: If Nomad API does not return valid JSON
    """
    method = method.upper()
    try:
        response = requests.request(method, url, params=data)
        return response.json()  # noqa: TC300
    except requests.exceptions.RequestException as e:
        log.error("Could not connect to Nomad API")  # noqa: TC400
        raise sys.exit(1) from e
    except requests.exceptions.JSONDecodeError as e:
        log.error("Could not decode JSON response from Nomad API")  # noqa: TC400
        raise sys.exit(1) from e
