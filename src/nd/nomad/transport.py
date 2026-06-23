"""Async HTTP transport for the Nomad API."""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING, Any, Self

import httpx2

from nd.nomad.errors import (
    NomadAuthError,
    NomadBadRequestError,
    NomadConnectionError,
    NomadHTTPError,
    NomadNotFoundError,
    NomadServerError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nd.nomad.config import NomadConfig


class AsyncTransport:
    """Thin async wrapper around ``httpx2.AsyncClient`` for the Nomad API."""

    def __init__(self, config: NomadConfig) -> None:
        self._config = config
        headers = {"X-Nomad-Token": config.token} if config.token else {}
        self._client = httpx2.AsyncClient(
            base_url=f"{config.address.rstrip('/')}/v1",
            headers=headers,
            timeout=config.timeout,
            verify=_build_verify(config),
            cert=_build_client_cert(config),
        )
        # Config is frozen, so namespace/region never change: build the base query
        # params once rather than rebuilding them on every request.
        self.default_params = _default_params(config)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,  # noqa: ANN401
    ) -> httpx2.Response:
        """Perform a request, raising typed errors on failure.

        Raises:
            NomadConnectionError: If the agent is unreachable.
            NomadHTTPError: If Nomad returns a non-2xx response.
        """
        merged = {**self.default_params, **(params or {})}
        extensions = (
            {"sni_hostname": self._config.tls_server_name} if self._config.tls_server_name else None
        )
        try:
            response = await self._client.request(
                method, path, params=merged, json=json, extensions=extensions
            )
        except httpx2.TransportError as exc:
            msg = f"Could not reach Nomad at {self._config.address}: {exc}"
            raise NomadConnectionError(msg) from exc

        if response.is_success:
            return response
        raise _http_error(method, path, response)

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[httpx2.Response]:
        """Yield successive pages, following Nomad's next-token pagination."""
        page_params = dict(params or {})
        while True:
            response = await self.request("GET", path, params=page_params)
            yield response
            next_token = response.headers.get("X-Nomad-Nexttoken")
            if not next_token:
                return
            page_params["next_token"] = next_token

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the async context manager, closing the client."""
        await self.aclose()


def _default_params(config: NomadConfig) -> dict[str, str]:
    """Build the query params applied to every request when namespace/region are set."""
    params: dict[str, str] = {}
    if config.namespace:
        params["namespace"] = config.namespace
    if config.region:
        params["region"] = config.region
    return params


def _build_verify(config: NomadConfig) -> ssl.SSLContext | bool:
    """Build the TLS verification context from the configured CA cert."""
    if config.ca_cert:
        return ssl.create_default_context(cafile=config.ca_cert)
    return True


def _build_client_cert(config: NomadConfig) -> tuple[str, str] | str | None:
    """Build the client certificate argument for mutual TLS."""
    if config.client_cert and config.client_key:
        return (config.client_cert, config.client_key)
    return config.client_cert


# Exact-match HTTP status -> typed exception; 5xx and anything else fall back below.
_STATUS_ERRORS: dict[int, type[NomadHTTPError]] = {
    400: NomadBadRequestError,
    403: NomadAuthError,
    404: NomadNotFoundError,
}


def _http_error(method: str, path: str, response: httpx2.Response) -> NomadHTTPError:
    """Map a non-2xx response to the matching typed exception."""
    status = response.status_code
    body = response.text
    message = f"Nomad {method} {path} returned {status}: {body}"
    error_cls = _STATUS_ERRORS.get(status) or (
        NomadServerError if status >= 500 else NomadHTTPError  # noqa: PLR2004
    )
    return error_cls(message, status_code=status, method=method, path=path, body=body)
