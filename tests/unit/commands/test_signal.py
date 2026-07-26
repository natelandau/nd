"""Tests for the nd signal command."""

import json
import re

import httpx
import pytest
import respx
import typer
from nclutils import pp
from rich.console import Console

from nd.cli import app
from nd.commands.signal import _normalize_signal
from nd.targets import ResolvedTarget

_ADDR = "http://nomad.test:4646"


def _patch_resolver(
    monkeypatch, *, target: ResolvedTarget | None, exit_code: int = 0
) -> dict[str, object]:
    """Patch resolve_with_client so tests exercise the command, not the picker.

    Mirrors the ``(exit_code, target)`` contract ``resolve_with_client`` returns: a
    non-zero ``exit_code`` simulates a selection failure or an unavailable prompt, both
    of which it has already reported via ``pp.error`` before returning. Returns the dict
    the fake populates with each call's arguments so a test can assert on it without
    reading shared module state.
    """
    from nd.commands import signal as signal_mod

    calls: dict[str, object] = {}

    async def _fake_resolve(
        client, *, job_arg, task_arg, running_only=True
    ) -> tuple[int, ResolvedTarget | None]:
        calls.update(job_arg=job_arg, task_arg=task_arg, running_only=running_only)
        return exit_code, target

    monkeypatch.setattr(signal_mod, "resolve_with_client", _fake_resolve)
    return calls


def _isolate_config(monkeypatch, tmp_path) -> None:
    """Point NomadConfig.resolve() at the mock address, not a real ~/.config/nd."""
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("SIGUSR1", "SIGUSR1"),
        ("sigusr1", "SIGUSR1"),
        ("USR1", "SIGUSR1"),
        ("usr1", "SIGUSR1"),
        (" sigterm ", "SIGTERM"),
        ("hup", "SIGHUP"),
        # Nomad accepts these; the local libc has no member for either
        ("signull", "SIGNULL"),
        ("iot", "SIGIOT"),
    ],
)
def test_normalize_signal_accepted_forms(given, expected):
    """Verify signal names normalize to their canonical SIG-prefixed uppercase form."""
    # Given a user-typed signal name in any case, with or without the SIG prefix
    # When normalizing it
    result = _normalize_signal(given)

    # Then it becomes the canonical name Nomad expects
    assert result == expected


@pytest.mark.parametrize("given", ["sigwat", "nope", "", "SIG", "SIGCHLD", "sigurg"])
def test_normalize_signal_rejects_unknown_names(given):
    """Verify a name Nomad will not deliver is a usage error rather than a request to it."""
    # Given a signal name Nomad's drivers do not accept
    # When normalizing it, Then it is rejected as a bad parameter
    with pytest.raises(typer.BadParameter):
        _normalize_signal(given)


def test_signal_sends_the_signal_to_the_resolved_task(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify the resolved allocation and task receive the requested signal."""
    # Given an isolated config, a resolved target, and a mocked signal endpoint
    _isolate_config(monkeypatch, tmp_path)
    _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))
    route = httpx2_mock.post(f"{_ADDR}/v1/client/allocation/alloc-1/signal").respond(json={})

    # When signaling the job by name
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1"])

    # Then it exits zero and posts the signal for that exact task
    assert result.exit_code == 0
    assert json.loads(route.calls.last.request.content) == {"Signal": "SIGUSR1", "Task": "ezbak"}


def test_signal_normalizes_the_signal_before_sending(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify a lowercase unprefixed signal reaches Nomad in canonical form."""
    # Given an isolated config, a resolved target, and a mocked signal endpoint
    _isolate_config(monkeypatch, tmp_path)
    _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))
    route = httpx2_mock.post(f"{_ADDR}/v1/client/allocation/alloc-1/signal").respond(json={})

    # When passing the signal as "usr1"
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "usr1"])

    # Then Nomad is sent SIGUSR1
    assert result.exit_code == 0
    assert json.loads(route.calls.last.request.content)["Signal"] == "SIGUSR1"


def test_signal_resolves_only_running_targets(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify the picker is restricted to running jobs, allocations, and tasks."""
    # Given an isolated config, a resolved target, and a mocked signal endpoint
    _isolate_config(monkeypatch, tmp_path)
    calls = _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))
    httpx2_mock.post(f"{_ADDR}/v1/client/allocation/alloc-1/signal").respond(json={})

    # When signaling with an explicit task
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1", "-t", "ezbak"])

    # Then the resolver was asked for live targets only, and got both arguments
    assert result.exit_code == 0
    assert calls == {"job_arg": "backup", "task_arg": "ezbak", "running_only": True}


def test_signal_requires_the_signal_option(monkeypatch, tmp_path, typer_runner):
    """Verify omitting -s is a usage error rather than a defaulted signal."""
    # Given an isolated config
    _isolate_config(monkeypatch, tmp_path)

    # When invoking with no signal
    result = typer_runner.invoke(app, ["signal", "backup"])

    # Then it is a usage error
    assert result.exit_code == 2


def test_signal_rejects_an_unknown_signal_before_any_request(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify a misspelled signal fails locally without contacting Nomad."""
    # Given an isolated config and a resolved target
    _isolate_config(monkeypatch, tmp_path)
    _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))

    # When passing a signal that does not exist
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGWAT"])

    # Then it is a usage error and nothing was sent
    assert result.exit_code == 2
    assert not httpx2_mock.calls


def test_signal_dry_run_resolves_but_sends_nothing(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify --dry-run resolves the target, then reports it without signaling it."""
    # Given an isolated config and a resolved target
    _isolate_config(monkeypatch, tmp_path)
    calls = _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))

    # When running with --dry-run
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1", "--dry-run"])

    # Then it exits zero, having resolved the target but sent nothing
    assert result.exit_code == 0
    assert calls == {"job_arg": "backup", "task_arg": None, "running_only": True}
    assert not httpx2_mock.calls


def test_signal_honors_a_nonzero_resolver_exit_code(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify a non-zero code from the resolver ends the command without signaling."""
    # Given an isolated config and a resolver reporting a selection failure
    _isolate_config(monkeypatch, tmp_path)
    _patch_resolver(monkeypatch, target=None, exit_code=1)

    # When signaling that name
    result = typer_runner.invoke(app, ["signal", "x", "-s", "SIGUSR1"])

    # Then it exits 1 and nothing was sent
    assert result.exit_code == 1
    assert not httpx2_mock.calls


def test_signal_named_job_not_running_exits_one(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify naming a job that is not running fails loudly rather than exiting zero."""
    # Given an isolated config and a cluster whose only job, matching the name, is dead
    _isolate_config(monkeypatch, tmp_path)
    httpx2_mock.get(f"{_ADDR}/v1/jobs").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "ID": "ezbak",
                    "Name": "ezbak",
                    "Type": "batch",
                    "Status": "dead",
                    "Priority": 50,
                    "CreateIndex": 1,
                    "ModifyIndex": 2,
                }
            ],
        )
    )

    # When signaling it unattended
    result = typer_runner.invoke(app, ["signal", "ezbak", "-s", "SIGUSR1"])

    # Then it exits 1 and never posts a signal
    assert result.exit_code == 1
    assert not [c for c in httpx2_mock.calls if c.request.method == "POST"]


def test_signal_cancelled_selection_exits_zero(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify cancelling the picker exits zero without signaling."""
    # Given an isolated config and a resolver reporting nothing selected
    _isolate_config(monkeypatch, tmp_path)
    _patch_resolver(monkeypatch, target=None)

    # When the user cancels
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1"])

    # Then it exits zero and nothing was sent
    assert result.exit_code == 0
    assert not httpx2_mock.calls


def test_signal_success_message_claims_delivery_only(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify the success line reports delivery, never that the signal acted on the task."""
    # Given an isolated config, a resolved target, and a mocked signal endpoint
    _isolate_config(monkeypatch, tmp_path)
    _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))
    httpx2_mock.post(f"{_ADDR}/v1/client/allocation/alloc-1/signal").respond(json={})
    capture = Console(theme=pp.THEME, record=True, force_terminal=True, width=100)
    emitter = pp.Emitter(console=capture, err_console=capture)
    original = pp.get_default()
    pp.set_default(emitter)

    # When signaling the resolved task
    try:
        result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1"])
    finally:
        pp.set_default(original)

    # Then the success line says the signal was sent, and never claims it acted on the task
    text = capture.export_text()
    assert result.exit_code == 0
    assert "Sent SIGUSR1 to task ezbak" in text
    lowered = text.lower()
    # Whole words only: these claims are substrings of ordinary words like "branch"
    for claim in ("triggered", "ran", "started"):
        assert not re.search(rf"\b{claim}\b", lowered)
