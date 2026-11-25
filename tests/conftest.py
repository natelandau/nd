"""Shared pytest fixtures that keep every test sealed off from the developer's machine."""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING

import pytest
from nclutils import pp

from nd.binary import env as binary_env_module
from nd.nomad.config import default_config_path
from tests.helpers import NOMAD_TEST_ADDR

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def isolate_nomad_config(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> None:
    """Keep the developer's NOMAD_* variables and nd config file out of every test."""
    for name in [name for name in os.environ if name.startswith("NOMAD_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg_config")))


@pytest.fixture(autouse=True)
def isolate_console_output() -> Iterator[None]:
    """Give each test a fresh `pp` emitter so verbosity or a capture console cannot leak."""
    original = pp.get_default()
    pp.set_default(pp.Emitter())
    yield
    pp.set_default(original)


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any real socket connection, so an unmocked request cannot reach a live cluster.

    respx intercepts mocked requests above the socket layer, so mocked tests never get here.
    """

    def _refuse(_sock: socket.socket, address: object) -> None:
        msg = f"Test opened a real network connection to {address!r}; mock it with httpx2_mock"
        raise RuntimeError(msg)

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)


@pytest.fixture(autouse=True)
def hide_nomad_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the developer's `nomad` binary, so a test that forgot to mock it fails cleanly."""
    monkeypatch.setattr(binary_env_module, "which", lambda _name: None)


@pytest.fixture
def job_files(tmp_path: Path) -> Callable[..., Path]:
    """Configure a job directory in the nd config and return a writer for job files in it.

    Call the writer as `write("web.hcl", "web", "worker")` to create a file defining those
    jobs; it returns the file's path.

    Returns:
        Callable[..., Path]: The job-file writer.
    """
    directory = tmp_path / "jobs"
    directory.mkdir()
    config_path = default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(f'[jobs]\ndirectories = ["{directory}"]\n', encoding="utf-8")

    def _write(filename: str, *job_names: str) -> Path:
        path = directory / filename
        path.write_text("".join(f'job "{name}" {{\n}}\n' for name in job_names), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def nomad_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point `NomadConfig.resolve()` at the mock cluster through `NOMAD_ADDR`.

    Returns:
        str: The mock cluster address.
    """
    monkeypatch.setenv("NOMAD_ADDR", NOMAD_TEST_ADDR)
    return NOMAD_TEST_ADDR
