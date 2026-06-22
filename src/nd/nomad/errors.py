"""Typed exceptions raised by the Nomad API client."""

from __future__ import annotations


class NomadError(Exception):
    """Base class for all Nomad client errors."""


class NomadConfigError(NomadError):
    """Raised when client configuration is missing or invalid."""


class NomadConnectionError(NomadError):
    """Raised when the client cannot reach the Nomad agent."""


class NomadDecodeError(NomadError):
    """Raised when a response body cannot be decoded into the expected type."""

    def __init__(self, message: str, *, payload: str | None = None) -> None:
        super().__init__(message)
        self.payload = payload


class NomadHTTPError(NomadError):
    """Raised when Nomad returns a non-2xx response."""

    def __init__(
        self, message: str, *, status_code: int, method: str, path: str, body: str
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.path = path
        self.body = body


class NomadBadRequestError(NomadHTTPError):
    """HTTP 400: request validation failed."""


class NomadAuthError(NomadHTTPError):
    """HTTP 403: client is not authenticated."""


class NomadNotFoundError(NomadHTTPError):
    """HTTP 404: unknown resource."""


class NomadServerError(NomadHTTPError):
    """HTTP 5xx: server-side failure."""
