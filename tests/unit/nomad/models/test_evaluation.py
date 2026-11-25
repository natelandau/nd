"""Tests for evaluation models."""

import msgspec
import pytest

from nd.nomad.models.evaluation import EvalListStub
from tests.builders import eval_stub


def test_eval_list_stub_decodes():
    """Verify EvalListStub decodes an evaluation listing stub with queued allocations."""
    # Given an evaluation-list stub payload
    payload = b"""
    {
      "ID": "eval-1", "JobID": "web", "Namespace": "default",
      "Status": "blocked", "Type": "service", "TriggeredBy": "job-register",
      "QueuedAllocations": {"web": 2}, "CreateIndex": 10, "ModifyIndex": 42
    }
    """
    # When decoding the payload
    stub = msgspec.json.decode(payload, type=EvalListStub)

    # Then the typed fields are populated
    assert stub.id == "eval-1"
    assert stub.status == "blocked"
    assert stub.type == "service"
    assert stub.queued_allocations == {"web": 2}


def test_eval_list_stub_defaults_queued_allocations():
    """Verify QueuedAllocations defaults to an empty dict when absent."""
    # Given a payload without QueuedAllocations
    payload = b"""
    {
      "ID": "eval-2", "JobID": "db", "Status": "complete", "Type": "service",
      "CreateIndex": 1, "ModifyIndex": 2
    }
    """
    # When decoding the payload
    stub = msgspec.json.decode(payload, type=EvalListStub)

    # Then queued allocations is an empty dict
    assert stub.queued_allocations == {}


@pytest.mark.parametrize(
    ("status", "queued", "expected"),
    [
        ("blocked", {}, True),
        ("pending", {}, True),
        ("complete", {"web": 1}, False),
        ("canceled", {"web": 1}, False),
        ("failed", {"web": 1}, False),
        ("running", {"web": 1}, True),
        ("running", {"web": 0}, False),
    ],
)
def test_eval_list_stub_is_problem(status: str, queued: dict[str, int], *, expected: bool) -> None:
    """Verify an evaluation is a problem when stuck or still holding queued allocations."""
    # Given an evaluation in the given status with the given queued counts
    evaluation = eval_stub(status=status, queued=queued)

    # When / Then only a live stuck evaluation is a problem
    assert evaluation.is_problem is expected
