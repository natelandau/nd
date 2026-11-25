"""Tests for the Nomad client exception hierarchy."""

import pytest

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
    # Then each piece of context is preserved
    assert err.status_code == 500
    assert err.method == "GET"
    assert err.path == "/v1/nodes"
    assert err.body == "oops"


@pytest.mark.parametrize(
    ("error_class", "parent_class"),
    [
        (NomadBadRequestError, NomadHTTPError),
        (NomadAuthError, NomadHTTPError),
        (NomadNotFoundError, NomadHTTPError),
        (NomadServerError, NomadHTTPError),
        (NomadHTTPError, NomadError),
        (NomadDecodeError, NomadError),
        (NomadConfigError, NomadError),
        (NomadConnectionError, NomadError),
    ],
)
def test_error_class_subclasses_its_parent(
    error_class: type[NomadError], parent_class: type[NomadError]
):
    """Verify each error subclasses its parent, so `main()` reports every one as a NomadError."""
    # Given an error class and the parent it belongs under
    # When checking the hierarchy
    # Then the class derives from that parent
    assert issubclass(error_class, parent_class)


def test_decode_error_carries_payload():
    """Verify NomadDecodeError retains the offending payload snippet."""
    # Given a decode error carrying a payload
    err = NomadDecodeError("bad", payload='{"a":1}')

    # When inspecting it
    # Then the payload is preserved
    assert err.payload == '{"a":1}'
