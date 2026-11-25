"""Tests for the shared subcommand wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nclutils import pp

from nd.commands._common import use_json_output

if TYPE_CHECKING:
    import pytest


def test_use_json_output_keeps_stdout_clean(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify JSON mode hides info lines and moves debug and trace output to stderr."""
    # Given trace verbosity and JSON mode
    pp.configure(verbosity=2)
    use_json_output()

    # When printing at every chatty level
    pp.info("hello")
    pp.debug("dbg")
    pp.trace("trc")

    # Then stdout is untouched and only debug and trace reach stderr
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "dbg" in captured.err
    assert "trc" in captured.err
    assert "hello" not in captured.err
