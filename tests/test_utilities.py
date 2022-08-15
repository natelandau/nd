# type: ignore
"""Test shared utility functions."""
import io
from pathlib import Path

from nd._commands.utils import utilities
from nd._commands.utils.job_files import JobFile


def test_select_one(monkeypatch) -> None:
    """Test select_one."""
    monkeypatch.setattr("sys.stdin", io.StringIO("item1"))
    items = ["item1", "item2", "item3"]
    assert utilities.select_one(items) == "item1"

    monkeypatch.setattr("sys.stdin", io.StringIO("job1"))
    job1 = JobFile("job1", Path("/dev/null"), local_backup=False)
    job2 = JobFile("job2", Path("/dev/null"), local_backup=False)
    items = [job1, job2]
    assert utilities.select_one(items) == job1

    assert utilities.select_one([]) is None

    assert utilities.select_one(["one_item"]) == "one_item"


# Prompt.ask
