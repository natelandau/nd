"""Tests for the Nomad client exception hierarchy."""

from nd.nomad.errors import (
    NomadAuthError,
    NomadBadRequestError,
    NomadConfigError,
    NomadConnectionError,
    NomadDecodeError,
    NomadError,
    NomadHTTPError,
    NomadNotFoundError,
    NomadServerError,
)


def test_http_error_carries_context():
    """Verify NomadHTTPError exposes the status, method, path, and body."""
    # Given an HTTP error built with full request context
    err = NomadHTTPError("boom", status_code=500, method="GET", path="/v1/nodes", body="oops")

    # When inspecting its attributes
    # Then each piece of context is preserved and it is a NomadError
    assert err.status_code == 500
    assert err.method == "GET"
    assert err.path == "/v1/nodes"
    assert err.body == "oops"
    assert isinstance(err, NomadError)


def test_http_subclasses_inherit_from_http_error():
    """Verify every status-specific error subclasses NomadHTTPError."""
    # Given the four status-specific HTTP error classes
    subclasses = (NomadBadRequestError, NomadAuthError, NomadNotFoundError, NomadServerError)

    # When instantiating each
    # Then all are NomadHTTPError instances
    for cls in subclasses:
        err = cls("x", status_code=400, method="GET", path="/p", body="")
        assert isinstance(err, NomadHTTPError)


def test_decode_error_carries_payload():
    """Verify NomadDecodeError retains the offending payload snippet."""
    # Given a decode error carrying a payload
    err = NomadDecodeError("bad", payload='{"a":1}')

    # When inspecting it
    # Then the payload is preserved and it is a NomadError
    assert err.payload == '{"a":1}'
    assert isinstance(err, NomadError)


def test_config_and_connection_errors_are_nomad_errors():
    """Verify the marker error subclasses derive from NomadError."""
    # Given the config and connection error classes
    # When instantiated
    # Then both are NomadError instances
    assert isinstance(NomadConfigError("x"), NomadError)
    assert isinstance(NomadConnectionError("x"), NomadError)
