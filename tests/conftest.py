"""Shared pytest fixtures that keep every test sealed off from the developer's machine."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from nclutils import pp

import nd.commands.run as run_module
from nd.binary import NomadBinary
from nd.binary import env as binary_env_module
from nd.nomad.config import default_config_path
from nd.ui import prompts as prompts_module
from tests.helpers import NOMAD_TEST_ADDR

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


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
    """Fail any real DNS lookup or socket connection, so a test cannot reach a live cluster.

    respx intercepts mocked requests above the socket layer, so mocked tests never get here.
    """

    def _refuse(*args: object, **_kwargs: object) -> None:
        # pytest.fail raises a BaseException, which CliRunner and `except Exception` handlers
        # cannot turn into an exit code a test might expect
        pytest.fail(f"Test made a real network call with {args!r}; mock it with httpx2_mock")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)


@pytest.fixture(autouse=True)
def hide_nomad_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the developer's `nomad` binary, so a test that forgot to mock it fails cleanly."""
    monkeypatch.setattr(binary_env_module, "which", lambda _name: None)


@pytest.fixture
def fake_nomad_binary(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> MagicMock:
    """Make `NomadBinary.create` return a mock, for commands that shell out to `nomad`.

    Returns:
        MagicMock: The binary every command receives; set return values and assert calls on it.
    """
    nomad = mocker.MagicMock(spec=NomadBinary)
    monkeypatch.setattr(NomadBinary, "create", classmethod(lambda _cls, _config: nomad))
    return nomad


@dataclass
class PromptAnswers:
    """What the prompt widgets answer in an interactive test session.

    `choice` is what a single-choice prompt returns, so `False` declines a confirmation.
    `choices` is what a multi-select returns; None selects every offered option.
    """

    choice: object = True
    choices: list[object] | None = None


@pytest.fixture
def interactive_session(monkeypatch: pytest.MonkeyPatch) -> PromptAnswers:
    """Act as an interactive terminal whose prompts answer with the returned `PromptAnswers`.

    Only the terminal check and the questionary widgets are replaced, so the prompt gating
    and the confirm and select logic under test run for real.

    Returns:
        PromptAnswers: The answers to give; set its fields before invoking the command.
    """
    answers = PromptAnswers()

    def _choose_many(choices: list[tuple[str, object]], _message: str) -> list[object]:
        if answers.choices is None:
            return [value for _label, value in choices]
        return answers.choices

    monkeypatch.setattr(prompts_module, "can_prompt", lambda: True)
    monkeypatch.setattr(run_module, "can_prompt", lambda: True)
    monkeypatch.setattr(prompts_module, "choose_one_from_list", lambda *_: answers.choice)
    monkeypatch.setattr(prompts_module, "choose_multiple_from_list", _choose_many)
    return answers


def _configure_directory(section: str, directory: Path) -> None:
    """Add a `[<section>] directories` entry for `directory` to the test's nd config file."""
    config_path = default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    entry = f'[{section}]\ndirectories = ["{directory}"]\n'
    config_path.write_text(existing + entry, encoding="utf-8")


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
    _configure_directory("jobs", directory)

    def _write(filename: str, *job_names: str) -> Path:
        path = directory / filename
        path.write_text("".join(f'job "{name}" {{\n}}\n' for name in job_names), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def volume_files(tmp_path: Path) -> Callable[[str], Path]:
    """Configure a host volume directory in the nd config and return a spec-file writer.

    Call the writer as `write("data")` to create `data.hcl`, a host volume spec named `data`
    whose relative path is also `data`; it returns the file's path.

    Returns:
        Callable[[str], Path]: The volume-spec writer.
    """
    directory = tmp_path / "volumes"
    directory.mkdir()
    _configure_directory("volumes", directory)

    def _write(name: str) -> Path:
        path = directory / f"{name}.hcl"
        path.write_text(
            f'name = "{name}"\ntype = "host"\n'
            'capability {\n  access_mode = "single-node-writer"\n'
            '  attachment_mode = "file-system"\n}\n'
            f'parameters {{\n  relative_path = "{name}"\n}}\n',
            encoding="utf-8",
        )
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
