"""Tests for the clean command."""

import pytest
import respx

from nd.commands import clean as clean_module
from tests.helpers import NOMAD_TEST_ADDR


@pytest.mark.usefixtures("nomad_env")
def test_clean_app_runs_gc_and_reconcile(httpx2_mock: respx.Router, typer_runner):
    """Verify clean forces GC and reconciles summaries, exiting zero."""
    # Given both housekeeping endpoints mocked
    gc = httpx2_mock.put(f"{NOMAD_TEST_ADDR}/v1/system/gc").respond(status_code=200)
    reconcile = httpx2_mock.put(f"{NOMAD_TEST_ADDR}/v1/system/reconcile/summaries").respond(
        status_code=200
    )

    # When invoking the clean command
    result = typer_runner.invoke(clean_module.app, [])

    # Then it exits zero and called both endpoints
    assert result.exit_code == 0
    assert gc.called
    assert reconcile.called


@pytest.mark.usefixtures("nomad_env")
def test_clean_app_exits_nonzero_on_error(httpx2_mock: respx.Router, typer_runner):
    """Verify a Nomad failure during clean exits non-zero."""
    # Given a GC endpoint that fails
    httpx2_mock.put(f"{NOMAD_TEST_ADDR}/v1/system/gc").respond(status_code=500, text="boom")

    # When invoking the clean command
    result = typer_runner.invoke(clean_module.app, [])

    # Then it exits non-zero
    assert result.exit_code != 0
