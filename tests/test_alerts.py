# type: ignore
"""Test alerts and logging."""
import re

import pytest

from nd._commands.utils import alerts
from nd._commands.utils.alerts import logger as log
from tests.helpers import Regex

# from pathlib import Path


def test_dryrun(capsys):
    """Test dry run."""
    dry_run = True
    alerts.dryrun(dry_run, "This prints in dry run")
    captured = capsys.readouterr()
    assert captured.out == "DRYRUN   |This prints in dry run\n"

    dry_run = False
    alerts.dryrun(dry_run, "This prints in dry run")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_success(capsys):
    """Test success."""
    alerts.success("This prints in success")
    captured = capsys.readouterr()
    assert captured.out == "SUCCESS  |This prints in success\n"


@pytest.mark.parametrize(
    ("verbosity", "log_to_file"),
    [(0, False), (1, False), (2, True), (3, True)],
)
def test_logging(capsys, tmp_path, verbosity, log_to_file) -> None:
    """Test logging."""
    tmp_log = tmp_path / "tmp.log"
    logging = alerts.LoggerManager(
        log_file=tmp_log,
        verbosity=verbosity,
        log_to_file=log_to_file,
    )

    assert logging.verbosity == verbosity

    if verbosity >= 3:
        assert logging.is_trace() is True
        captured = capsys.readouterr()
        assert captured.out == ""

        assert logging.is_trace("trace text") is True
        captured = capsys.readouterr()
        assert captured.out == "trace text\n"

        log.trace("This is Trace logging")
        captured = capsys.readouterr()
        assert captured.err == Regex(r"^TRACE    \| This is Trace logging \([\w\._:]+:\d+\)$")
    else:
        assert logging.is_trace("trace text") is False
        captured = capsys.readouterr()
        assert captured.out != "trace text\n"

        log.trace("This is Trace logging")
        captured = capsys.readouterr()
        assert captured.err != Regex(r"^TRACE    \| This is Trace logging \([\w\._:]+:\d+\)$")

    if verbosity >= 2:
        assert logging.is_debug() is True
        captured = capsys.readouterr()
        assert captured.out == ""

        assert logging.is_debug("debug text") is True
        captured = capsys.readouterr()
        assert captured.out == "debug text\n"

        log.debug("This is Debug logging")
        captured = capsys.readouterr()
        assert captured.err == Regex(r"^DEBUG    \| This is Debug logging \([\w\._:]+:\d+\)$")
    else:
        assert logging.is_debug("debug text") is False
        captured = capsys.readouterr()
        assert captured.out != "debug text\n"

        log.debug("This is Debug logging")
        captured = capsys.readouterr()
        assert captured.err != Regex(r"^DEBUG    \| This is Debug logging \([\w\._:]+:\d+\)$")

    if verbosity >= 1:
        assert logging.is_info() is True
        captured = capsys.readouterr()
        assert captured.out == ""

        assert logging.is_info("info text") is True
        captured = capsys.readouterr()
        assert captured.out == "info text\n"

        log.info("This is Info logging")
        captured = capsys.readouterr()
        assert captured.err == "INFO     | This is Info logging\n"

        # log.success("This is Success logging")
        # captured = capsys.readouterr()
        # assert captured.out == "SUCCESS  | This is Success logging\n"
    else:
        assert logging.is_info("info text") is False
        captured = capsys.readouterr()
        assert captured.out != "info text\n"

        log.info("This is Info logging")
        captured = capsys.readouterr()
        assert captured.out == ""

        # log.success("This is Success logging")
        # captured = capsys.readouterr()
        # assert captured.out == ""

    assert logging.is_default() is True
    captured = capsys.readouterr()
    assert captured.out == ""

    assert logging.is_default("default text") is True
    captured = capsys.readouterr()
    assert captured.out == "default text\n"

    if log_to_file:
        assert tmp_log.exists() is True
        log_file_content = tmp_log.read_text()
        assert log_file_content == Regex(
            r"^\d{4}-\d{2}-\d{2} \d+:\d+:\d+\.\d+ \| DEBUG    \| [\w\.:]+:\d+ \- Logging to file:",
            re.MULTILINE,
        )
    else:
        assert tmp_log.exists() is False
