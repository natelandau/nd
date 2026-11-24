"""Shared pytest fixtures."""

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_nomad_config(monkeypatch, tmp_path_factory):
    """Keep the developer's NOMAD_* variables and nd config file out of every test."""
    for name in [name for name in os.environ if name.startswith("NOMAD_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg_config")))
