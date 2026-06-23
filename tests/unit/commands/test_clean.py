"""Tests for the clean command."""

import respx
from typer.testing import CliRunner

from nd.commands import clean as clean_module

_ADDR = "http://nomad.test:4646"


def test_clean_app_runs_gc_and_reconcile(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify clean forces GC and reconciles summaries, exiting zero."""
    # Given an isolated config and both housekeeping endpoints mocked
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    gc = httpx2_mock.put(f"{_ADDR}/v1/system/gc").respond(status_code=200)
    reconcile = httpx2_mock.put(f"{_ADDR}/v1/system/reconcile/summaries").respond(status_code=200)

    # When invoking the clean command
    result = CliRunner().invoke(clean_module.app, [])

    # Then it exits zero and called both endpoints
    assert result.exit_code == 0
    assert gc.called
    assert reconcile.called


def test_clean_app_exits_nonzero_on_error(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify a Nomad failure during clean exits non-zero."""
    # Given an isolated config where the GC endpoint fails
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.put(f"{_ADDR}/v1/system/gc").respond(status_code=500, text="boom")

    # When invoking the clean command
    result = CliRunner().invoke(clean_module.app, [])

    # Then it exits non-zero
    assert result.exit_code != 0
