"""Tests for the shared subcommand wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nclutils import pp

from nd.commands._common import configure_verbosity

if TYPE_CHECKING:
    import pytest
    from pytest_mock import MockerFixture


def test_configure_verbosity_json_output_keeps_stdout_clean(
    capsys: pytest.CaptureFixture[str], mocker: MockerFixture
) -> None:
    """Verify JSON mode hides info lines and moves debug and trace output to stderr."""
    # Given trace verbosity and JSON mode
    configure_verbosity(mocker.Mock(obj=None), 2, json_output=True)

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
