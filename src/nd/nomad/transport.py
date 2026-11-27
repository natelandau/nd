"""Async HTTP transport for the Nomad API."""

from __future__ import annotations

import ssl
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any, Self

import httpx2

from nd.constants import BLOCKING_QUERY_TIMEOUT_MARGIN_SECONDS
from nd.nomad.errors import (
    NomadAuthError,
    NomadBadRequestError,
    NomadConnectionError,
    NomadDecodeError,
    NomadHTTPError,
    NomadNotFoundError,
    NomadServerError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Generator
    from contextlib import AbstractAsyncContextManager

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
            # Each followed log holds a connection open, so a log view of a large job would
            # exhaust a capped pool and starve its own allocation watch
            limits=httpx2.Limits(max_connections=None, max_keepalive_connections=20),
            verify=_build_verify(config),
            cert=_build_client_cert(config),
        )
        # Config is frozen, so build the per-request params and extensions once.
        self.default_params = _default_params(config)
        self._extensions = (
            {"sni_hostname": config.tls_server_name} if config.tls_server_name else None
        )

    def _params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        return {**self.default_params, **(params or {})}

    @contextmanager
    def _mapping_transport_errors(self) -> Generator[None]:
        try:
            yield
        except httpx2.TransportError as exc:
            msg = f"Could not reach Nomad at {self._config.address}: {exc}"
            raise NomadConnectionError(msg) from exc

    @staticmethod
    async def _raise_for_status(method: str, path: str, response: httpx2.Response) -> None:
        if not response.is_success:
            # A streamed body is not read yet, and the error carries it
            await response.aread()
            raise _http_error(method, path, response)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,  # noqa: ANN401
        content: bytes | None = None,
        request_timeout: float | None = None,
    ) -> httpx2.Response:
        """Perform a request, raising typed errors on failure.

        Pass ``content`` instead of ``json`` to send an already-encoded JSON body as is.
        Pass ``request_timeout`` for a request that Nomad holds open on purpose, such as a blocking
        query, so the configured timeout cannot cut it short; None keeps the configured one.

        Raises:
            NomadConnectionError: If the agent is unreachable.
            NomadHTTPError: If Nomad returns a non-2xx response.
        """
        headers = {"Content-Type": "application/json"} if content is not None else None
        with self._mapping_transport_errors():
            response = await self._client.request(
                method=method,
                url=path,
                params=self._params(params),
                json=json,
                content=content,
                headers=headers,
                timeout=httpx2.USE_CLIENT_DEFAULT if request_timeout is None else request_timeout,
                extensions=self._extensions,
            )
        await self._raise_for_status(method, path, response)
        return response

    async def blocking_request(
        self, path: str, *, index: int, wait_seconds: int, params: dict[str, Any] | None = None
    ) -> tuple[httpx2.Response, int]:
        """Run a blocking GET query that Nomad holds open until its data changes past ``index``.

        Use it to watch a resource in a loop, passing back the returned index each time;
        index 0 returns at once. The request timeout is longer than the wait, whatever
        timeout the client has.

        Args:
            path: The API path to query.
            index: The index from the previous call, or 0 for the current state.
            wait_seconds: The longest time Nomad holds the request open.
            params: Extra query parameters.

        Returns:
            tuple[httpx2.Response, int]: The response and the index to pass next, never
            below 1 so a server that sends 0 cannot make the next query return at once.

        Raises:
            NomadConnectionError: If the agent is unreachable.
            NomadHTTPError: If Nomad returns a non-2xx response.
            NomadDecodeError: If the response has no numeric ``X-Nomad-Index`` header.
        """
        response = await self.request(
            "GET",
            path,
            params={**(params or {}), "index": index, "wait": f"{wait_seconds}s"},
            request_timeout=wait_seconds + BLOCKING_QUERY_TIMEOUT_MARGIN_SECONDS,
        )
        raw_index = response.headers.get("X-Nomad-Index", "")
        try:
            new_index = int(raw_index)
        except ValueError as exc:
            msg = f"Expected a numeric X-Nomad-Index header from {path}, got {raw_index!r}"
            raise NomadDecodeError(msg) from exc
        return response, max(new_index, 1)

    def stream(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> AbstractAsyncContextManager[AsyncIterator[bytes]]:
        """Open a long-lived response and yield its body chunks as they arrive.

        Use it for endpoints that never finish on their own, such as followed logs. The
        read timeout is disabled so a quiet stream stays open; the connect timeout still
        applies.

        Raises:
            NomadConnectionError: If the agent is unreachable or the stream drops.
            NomadHTTPError: If Nomad returns a non-2xx response.
        """
        return self._stream(method, path, params)

    @asynccontextmanager
    async def _stream(
        self, method: str, path: str, params: dict[str, Any] | None
    ) -> AsyncGenerator[AsyncIterator[bytes]]:
        timeout = httpx2.Timeout(self._config.timeout, read=None)
        with self._mapping_transport_errors():
            async with self._client.stream(
                method=method,
                url=path,
                params=self._params(params),
                timeout=timeout,
                extensions=self._extensions,
            ) as response:
                await self._raise_for_status(method, path, response)
                yield response.aiter_bytes()

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[httpx2.Response]:
        """Yield successive pages, following Nomad's next-token pagination."""
        page_params = dict(params or {})
        while True:
            response = await self.request(method="GET", path=path, params=page_params)
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
