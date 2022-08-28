# type: ignore
"""Test shared utility functions."""
import io
from pathlib import Path

from nd._utils import utilities
from nd._utils.job_files import JobFile


def test_select_one_jobfile(monkeypatch, mock_jobs) -> None:
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

    monkeypatch.setattr("sys.stdin", io.StringIO("job1"))
    jobs = mock_jobs
    assert utilities.select_one(jobs) == jobs[0]


def test_chunks():
    """Test chunks()."""
    test_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert list(utilities.chunks(test_list, 2)) == [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10], [11]]
    assert list(utilities.chunks(test_list, 3)) == [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11]]
    assert list(utilities.chunks(test_list, 5)) == [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11]]
    assert list(utilities.chunks(test_list, 11)) == [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]]
