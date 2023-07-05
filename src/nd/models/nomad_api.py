"""Representation of the Nomad API."""

from typing import Any

import requests
import typer

from nd.utils import alerts
from nd.utils.alerts import logger as log


class NomadAPI:  # pragma: no cover
    """Representation of the Nomad API."""

    def __init__(self, url: str, token: str | None = None, dry_run: bool = False) -> None:
        self.url = url
        self.token = token
        self.dry_run = dry_run

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Send a GET request to the Nomad API.

        Args:
            path (str): The path to the API endpoint.
            params (dict, optional): Query parameters to send to the API. Defaults to None.

        Returns:
            dict: The JSON response from the API.
        """
        headers = {"X-Nomad-Token": self.token} if self.token else None
        try:
            response = requests.get(
                f"{self.url}/{path}", headers=headers, params=params, timeout=10
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as e:
            log.error(f"Request to {self.url}/{path} timed out\n{e}")
            raise typer.Exit(1) from e
        except requests.exceptions.HTTPError as e:
            log.error(f"API Response:\n{e}")
            raise typer.Exit(1) from e
        except requests.exceptions.ConnectionError as e:
            log.error(f"Could not connect to Nomad API at {self.url}")
            raise typer.Exit(1) from e

        log.trace(f"API Response:\n{response}")

        if response.ok and response.text:
            try:
                return response.json()
            except ValueError as e:
                log.error("Nomad API did not return valid JSON")
                raise typer.Exit(1) from e

            except requests.exceptions.JSONDecodeError as e:
                log.error("Could not decode JSON response from Nomad API")
                raise typer.Exit(1) from e
        elif response.ok and not response.text:
            return None

        return response.json()

    def _post(self, path: str, data: dict | None = None, params: dict | None = None) -> dict:
        """Send a POST request to the Nomad API.

        Args:
            path (str): The path to the API endpoint.
            data (dict, optional): The data to send to the API. Defaults to None.
            params (dict, optional): Query parameters to send to the API. Defaults to None.

        Returns:
            dict: The JSON response from the API.
        """
        headers = {"X-Nomad-Token": self.token} if self.token else None
        try:
            response = requests.post(
                f"{self.url}/{path}", headers=headers, json=data, params=params, timeout=10
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as e:
            log.error(f"Request to {self.url}/{path} timed out\n{e}")
            raise typer.Exit(1) from e
        except requests.exceptions.HTTPError as e:
            log.error(f"API Response:\n{e}")
            raise typer.Exit(1) from e
        except requests.exceptions.ConnectionError as e:
            log.error(f"Could not connect to Nomad API at {self.url}")
            raise typer.Exit(1) from e
        return response.json()

    def _put(self, path: str, data: dict | None = None, params: dict | None = None) -> dict:
        """Send a PUT request to the Nomad API.

        Args:
            path (str): The path to the API endpoint.
            data (dict, optional): The data to send to the API. Defaults to None.
            params (dict, optional): Query parameters to send to the API. Defaults to None.

        Returns:
            dict: The JSON response from the API.
        """
        headers = {"X-Nomad-Token": self.token} if self.token else None
        try:
            response = requests.put(
                f"{self.url}/{path}", headers=headers, json=data, params=params, timeout=10
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as e:
            log.error(f"Request to {self.url}/{path} timed out\n{e}")
            raise typer.Exit(1) from e
        except requests.exceptions.HTTPError as e:
            log.error(f"API Response:\n{e}")
            raise typer.Exit(1) from e
        except requests.exceptions.ConnectionError as e:
            log.error(f"Could not connect to Nomad API at {self.url}")
            raise typer.Exit(1) from e

        log.trace(f"API Response:\n{response}")

        if response.ok and response.text:
            try:
                return response.json()
            except ValueError as e:
                log.error("Nomad API did not return valid JSON")
                raise typer.Exit(1) from e

            except requests.exceptions.JSONDecodeError as e:
                log.error("Could not decode JSON response from Nomad API")
                raise typer.Exit(1) from e
        elif response.ok and not response.text:
            return None

        return response.json()

    def _delete(self, path: str, data: dict | None = None, params: dict | None = None) -> dict:
        """Send a DELETE request to the Nomad API.

        Args:
            path (str): The path to the API endpoint.
            data (dict, optional): The data to send to the API. Defaults to None.
            params (dict, optional): Query parameters to send to the API. Defaults to None.

        Returns:
            dict: The JSON response from the API.
        """
        headers = {"X-Nomad-Token": self.token} if self.token else None
        try:
            response = requests.delete(
                f"{self.url}/{path}", headers=headers, json=data, params=params, timeout=10
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as e:
            log.error(f"Request to {self.url}/{path} timed out\n{e}")
            raise typer.Exit(1) from e
        except requests.exceptions.HTTPError as e:
            log.error(f"API Response:\n{e}")
            raise typer.Exit(1) from e
        except requests.exceptions.ConnectionError as e:
            log.error(f"Could not connect to Nomad API at {self.url}")
            raise typer.Exit(1) from e

        return response.json()

    def garbage_collect(self) -> bool:
        """Trigger garbage collection."""
        try:
            self._put("v1/system/gc")
        except requests.exceptions.HTTPError:
            return False

        return True

    def get_allocations(self, job_id: str, data: dict | None = None) -> dict[Any, Any]:
        """Query the Nomad API for a list of allocations.

        Args:
            job_id (str): The ID of the job to query.
            data (dict, optional): Query parameters to pass to the API. Defaults to None.

        Returns:
            dict[Any, Any]: Response from the Nomad API.
        """
        return self._get(f"v1/job/{job_id}/allocations", params=data)

    def get_jobs(self, data: dict | None = None) -> dict[Any, Any]:
        """Query the Nomad API for a list of jobs.

        Args:
            data (dict, optional): Query parameters to pass to the API. Defaults to None.

        Returns:
            dict[Any, Any]: Response from the Nomad API.
        """
        return self._get("v1/jobs", params=data)

    def get_nodes(self, data: dict | None = None) -> dict[Any, Any]:
        """Query the Nomad API for a list of nodes.

        Args:
            data (dict, optional): Query parameters to pass to the API. Defaults to None.

        Returns:
            dict[Any, Any]: Response from the Nomad API.
        """
        return self._get("v1/nodes", params=data)

    def stop_job(self, job_id: str, params: dict | None = None) -> bool:
        """Stop a job.

        Args:
            params (dict, optional): Query parameters to pass to the API. Defaults to None.
            job_id (str): The ID of the job to stop.

        Returns:
            bool: True if the job was stopped, False otherwise.
        """
        if self.dry_run:
            alerts.dryrun(f"Would stop job {job_id}")
            return True

        result = self._delete(f"v1/job/{job_id}", params=params)
        log.trace(f"API Response:\n{result}")

        return True
