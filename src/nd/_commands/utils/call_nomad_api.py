"""Functions to work with the Nomad API."""
import sys

import requests

from nd._commands.utils.alerts import logger as log


def make_nomad_api_call(
    url: str,
    method: str,
    data: dict | None = None,
) -> list | bool:
    """Make a call to the Nomad HTTP API.

    Args:
        url (str): The URL to make the call to.
        method (str): The HTTP method to use.
        data (dict): The data to send with the request.

    Examples:
        nomad_api_call("/jobs")
        nomad_api_call("/jobs", {"prefix": "sonarr"})

    Returns:
        list: The response from the Nomad API.

    Raises:
        exit: If the Nomad API is not available.
        exit: If Nomad API does not return valid JSON
    """
    method = method.upper()

    try:
        log.trace(f"Making {method} request to {url}")
        response = requests.request(method, url, params=data)
    except requests.exceptions.RequestException as e:
        log.error("Could not connect to Nomad API")  # noqa: TC400
        raise sys.exit(1) from e

    if response.ok and response.text:
        try:
            return response.json()
        except ValueError as e:
            log.error("Nomad API did not return valid JSON")  # noqa: TC400
            raise sys.exit(1) from e
        except requests.exceptions.JSONDecodeError as e:
            log.error("Could not decode JSON response from Nomad API")  # noqa: TC400
            raise sys.exit(1) from e
    elif response.ok and not response.text:
        return True
    else:
        log.error(f"Nomad API returned {response.status_code}")
        raise sys.exit(1)
