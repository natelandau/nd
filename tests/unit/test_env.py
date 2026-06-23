"""Tests for the shared nomad-binary discovery and environment helpers."""

from __future__ import annotations

import pytest

from nd.binary import NomadBinaryError, env
from nd.nomad.config import NomadConfig


def test_ensure_nomad_missing_raises(monkeypatch) -> None:
    """Verify a missing nomad binary raises NomadBinaryError."""
    # Given nomad is not on PATH
    monkeypatch.setattr(env, "which", lambda name: None)

    # When / Then resolving it raises a friendly error
    with pytest.raises(NomadBinaryError, match="nomad"):
        env.ensure_nomad()


def test_binary_env_overlays_config_onto_environment(monkeypatch) -> None:
    """Verify binary_env overlays the resolved config onto the ambient environment."""
    # Given an ambient environment with a sentinel variable
    monkeypatch.setenv("SENTINEL_VAR", "keep-me")
    config = NomadConfig(address="http://nomad.test:4646", token="t")  # noqa: S106

    # When building the binary environment
    result = env.binary_env(config)

    # Then the config targets the cluster and the ambient variables are preserved
    assert result["NOMAD_ADDR"] == "http://nomad.test:4646"
    assert result["NOMAD_TOKEN"] == "t"  # noqa: S105
    assert result["SENTINEL_VAR"] == "keep-me"
