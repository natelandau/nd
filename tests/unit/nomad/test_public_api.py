"""Tests for the public nd.nomad surface."""

from nd import nomad

_EXPECTED_ALL = {
    "NomadClient",
    "NomadConfig",
    "NomadError",
    "NomadConfigError",
    "NomadConnectionError",
    "NomadDecodeError",
    "NomadHTTPError",
    "NomadBadRequestError",
    "NomadAuthError",
    "NomadNotFoundError",
    "NomadServerError",
}


def test_all_contains_exactly_expected_names():
    """Verify that __all__ contains exactly the 11 expected public names."""
    # Given: the nomad module
    # When: reading the __all__ definition
    # Then: it should match exactly the expected set
    assert set(nomad.__all__) == _EXPECTED_ALL


def test_all_names_are_accessible_on_module():
    """Verify that every name in __all__ is accessible as an attribute on the module."""
    # Given: the nomad module
    # When: iterating over __all__
    # Then: each name should be present as an attribute
    for name in nomad.__all__:
        assert hasattr(nomad, name), f"nomad.{name} is listed in __all__ but not accessible"
