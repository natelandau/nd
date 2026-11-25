"""Tests for allocation models."""

import msgspec
import pytest

from nd.nomad.models.allocation import AllocListStub, TaskState
from tests.builders import alloc_stub


def test_alloc_list_stub_decodes_irregular_keys():
    """Verify AllocListStub decodes API keys with pascal-case renaming."""
    # Given
    payload = b"""
    {
      "ID": "alloc-1", "Name": "web.web[0]", "Namespace": "default",
      "NodeID": "node-1", "JobID": "web", "TaskGroup": "web",
      "ClientStatus": "running", "DesiredStatus": "run",
      "CreateIndex": 7, "ModifyIndex": 11, "Unknown": true
    }
    """
    # When
    stub = msgspec.json.decode(payload, type=AllocListStub)
    # Then
    assert stub.node_id == "node-1"
    assert stub.job_id == "web"
    assert stub.client_status == "running"


def test_alloc_list_stub_decodes_task_states():
    """Verify the allocation list stub decodes per-task states when present."""
    # Given a job-allocations stub payload that includes TaskStates
    payload = b"""
    {
      "ID": "a1", "Name": "web.web[0]", "Namespace": "default", "NodeID": "n1",
      "JobID": "web", "TaskGroup": "web", "ClientStatus": "running",
      "DesiredStatus": "stop", "CreateIndex": 1, "ModifyIndex": 2,
      "TaskStates": {"cleanup": {"State": "running", "Failed": false, "Restarts": 0}}
    }
    """

    # When decoding
    stub = msgspec.json.decode(payload, type=AllocListStub)

    # Then the task state decodes
    assert stub.task_states["cleanup"].state == "running"


def test_alloc_list_stub_decodes_task_events_and_deployment_health():
    """Verify task events, the job version, and deployment health decode, nulls included."""
    # Given a stub payload with events on one task, null events on another, and health
    payload = b"""
    {
      "ID": "a1", "Name": "web.web[0]", "NodeID": "n1", "JobID": "web",
      "TaskGroup": "web", "JobVersion": 3, "ClientStatus": "failed",
      "DesiredStatus": "run", "CreateIndex": 1, "ModifyIndex": 2,
      "DeploymentStatus": {"Healthy": false, "Canary": false},
      "TaskStates": {
        "app": {"State": "dead", "Failed": true, "Restarts": 0, "Events": [
          {"Type": "Terminated", "Time": 1636017249803624000,
           "DisplayMessage": "Exit Code: 1", "ExitCode": 1}
        ]},
        "sidecar": {"State": "pending", "Failed": false, "Restarts": 0, "Events": null}
      }
    }
    """

    # When decoding
    stub = msgspec.json.decode(payload, type=AllocListStub)

    # Then the events, version, and health decode, and null events read as none
    event = stub.task_states["app"].events[0]
    assert (event.type, event.display_message) == ("Terminated", "Exit Code: 1")
    assert stub.task_states["sidecar"].events == []
    assert stub.job_version == 3
    assert stub.deployment_status is not None
    assert stub.deployment_status.healthy is False


def test_alloc_list_stub_defaults_task_states_empty():
    """Verify the allocation list stub defaults task_states to an empty dict."""
    # Given a stub payload with no TaskStates
    payload = b"""
    {
      "ID": "a1", "Name": "web.web[0]", "NodeID": "n1", "JobID": "web",
      "TaskGroup": "web", "ClientStatus": "complete", "DesiredStatus": "stop",
      "CreateIndex": 1, "ModifyIndex": 2
    }
    """

    # When decoding
    stub = msgspec.json.decode(payload, type=AllocListStub)

    # Then task_states is empty
    assert stub.task_states == {}


def test_alloc_list_stub_decodes_create_time():
    """Verify the allocation list stub decodes CreateTime into create_time nanoseconds."""
    # Given a stub payload carrying a CreateTime unix-nanosecond timestamp
    payload = b"""
    {
      "ID": "a1", "Name": "web.web[0]", "NodeID": "n1", "JobID": "web",
      "TaskGroup": "web", "ClientStatus": "running", "DesiredStatus": "run",
      "CreateIndex": 1, "ModifyIndex": 2, "CreateTime": 1717243200000000000
    }
    """

    # When decoding
    stub = msgspec.json.decode(payload, type=AllocListStub)

    # Then create_time carries the raw nanoseconds, defaulting to 0 when absent
    assert stub.create_time == 1717243200000000000


def test_alloc_list_stub_defaults_create_time_zero():
    """Verify the allocation list stub defaults create_time to 0 when CreateTime is absent."""
    # Given a stub payload with no CreateTime
    payload = b"""
    {
      "ID": "a1", "Name": "web.web[0]", "NodeID": "n1", "JobID": "web",
      "TaskGroup": "web", "ClientStatus": "running", "DesiredStatus": "run",
      "CreateIndex": 1, "ModifyIndex": 2
    }
    """

    # When decoding
    stub = msgspec.json.decode(payload, type=AllocListStub)

    # Then create_time is 0
    assert stub.create_time == 0


def test_task_state_decodes_started_at():
    """Verify TaskState decodes the StartedAt RFC3339 timestamp, defaulting to empty."""
    # Given a stub payload whose task state carries a StartedAt timestamp
    payload = b"""
    {
      "ID": "a1", "Name": "web.web[0]", "NodeID": "n1", "JobID": "web",
      "TaskGroup": "web", "ClientStatus": "running", "DesiredStatus": "run",
      "CreateIndex": 1, "ModifyIndex": 2,
      "TaskStates": {"server": {"State": "running", "Failed": false, "Restarts": 0,
        "StartedAt": "2024-06-01T12:00:00.000000000Z"}}
    }
    """

    # When decoding
    stub = msgspec.json.decode(payload, type=AllocListStub)

    # Then the task state exposes the raw StartedAt string
    assert stub.task_states["server"].started_at == "2024-06-01T12:00:00.000000000Z"


def test_task_state_decodes_null_started_at():
    """Verify TaskState coerces an explicit null StartedAt to an empty string."""
    # Given a task Nomad has not started yet, so it sends StartedAt: null (not an absent key)
    payload = b"""
    {
      "ID": "a1", "Name": "web.web[0]", "NodeID": "n1", "JobID": "web",
      "TaskGroup": "web", "ClientStatus": "pending", "DesiredStatus": "run",
      "CreateIndex": 1, "ModifyIndex": 2,
      "TaskStates": {"server": {"State": "pending", "Failed": false, "Restarts": 0,
        "StartedAt": null}}
    }
    """

    # When decoding
    stub = msgspec.json.decode(payload, type=AllocListStub)

    # Then started_at is the empty-string default rather than raising a decode error
    assert stub.task_states["server"].started_at == ""


def test_task_state_defaults_started_at_empty():
    """Verify TaskState defaults started_at to an empty string when StartedAt is absent."""
    # Given a task state with no StartedAt
    payload = b"""
    {
      "ID": "a1", "Name": "web.web[0]", "NodeID": "n1", "JobID": "web",
      "TaskGroup": "web", "ClientStatus": "running", "DesiredStatus": "run",
      "CreateIndex": 1, "ModifyIndex": 2,
      "TaskStates": {"server": {"State": "running", "Failed": false, "Restarts": 0}}
    }
    """

    # When decoding
    stub = msgspec.json.decode(payload, type=AllocListStub)

    # Then started_at is the empty-string default
    assert stub.task_states["server"].started_at == ""


def test_alloc_list_stub_decodes_null_task_states():
    """Verify the allocation list stub coerces an explicit null TaskStates to an empty dict."""
    # Given a freshly-placed alloc whose tasks have not started, so Nomad sends null
    payload = b"""
    {
      "ID": "a1", "Name": "web.web[0]", "NodeID": "n1", "JobID": "web",
      "TaskGroup": "web", "ClientStatus": "pending", "DesiredStatus": "run",
      "CreateIndex": 1, "ModifyIndex": 2, "TaskStates": null
    }
    """

    # When decoding
    stub = msgspec.json.decode(payload, type=AllocListStub)

    # Then task_states is an empty dict rather than raising a decode error
    assert stub.task_states == {}


@pytest.mark.parametrize(
    ("client_status", "expected"),
    [
        ("complete", True),
        ("failed", True),
        ("lost", True),
        ("running", False),
        ("pending", False),
    ],
)
def test_alloc_list_stub_is_terminal(client_status: str, *, expected: bool) -> None:
    """Verify only complete, failed, and lost allocations count as fully stopped."""
    # Given an allocation in the given client status
    alloc = msgspec.convert(
        {
            "ID": "a1",
            "Name": "web.web[0]",
            "NodeID": "n1",
            "JobID": "web",
            "TaskGroup": "web",
            "ClientStatus": client_status,
            "DesiredStatus": "stop",
            "CreateIndex": 1,
            "ModifyIndex": 2,
        },
        type=AllocListStub,
    )

    # When / Then it reports terminal only for a stopped client status
    assert alloc.is_terminal is expected


@pytest.mark.parametrize(
    ("started_at", "expected_ns"),
    [
        ("1970-01-01T00:00:01Z", 1_000_000_000),
        ("1970-01-01T00:00:00.5Z", 500_000_000),
        # Sub-microsecond digits are truncated
        ("1970-01-01T00:00:00.123456789Z", 123_456_000),
        # A non-UTC offset normalizes to the same instant
        ("1970-01-01T05:00:01+05:00", 1_000_000_000),
        # Nomad's not-started sentinel, blanks, and garbage read as unusable
        ("0001-01-01T00:00:00Z", 0),
        ("", 0),
        ("not-a-timestamp", 0),
        # A timestamp with no offset has no knowable instant
        ("2024-06-01T12:00:00", 0),
        ("2024-06-01T12:00:00.123456789", 0),
    ],
)
def test_task_state_started_at_ns(started_at: str, expected_ns: int) -> None:
    """Verify started_at_ns converts StartedAt to exact unix nanoseconds, or 0 when unusable."""
    # Given a task state carrying the StartedAt value
    state = TaskState(state="running", failed=False, restarts=0, started_at_raw=started_at)

    # When / Then the nanosecond anchor matches
    assert state.started_at_ns == expected_ns


@pytest.mark.parametrize(
    ("last_restart", "expected_ns"),
    [
        (None, 0),
        ("", 0),
        ("0001-01-01T00:00:00Z", 0),
        ("garbage", 0),
        ("2026-11-24T10:00:00", 0),
        ("1970-01-01T00:00:02Z", 2_000_000_000),
    ],
)
def test_task_state_last_restart_ns(last_restart: str | None, expected_ns: int) -> None:
    """Verify a task's last restart reads as unix nanoseconds, or 0 when unusable."""
    # Given a task state carrying the given LastRestart value
    payload = {"State": "running", "Failed": False, "Restarts": 3, "LastRestart": last_restart}

    # When decoding it
    state = msgspec.convert(payload, type=TaskState)

    # Then the restart time is exact, or 0 for a missing or unusable timestamp
    assert state.last_restart_ns == expected_ns


@pytest.mark.parametrize(
    ("client_status", "desired_status", "next_allocation", "expected"),
    [
        ("failed", "run", "", True),
        ("lost", "run", "", True),
        ("failed", "run", "a2", False),
        ("failed", "stop", "", False),
        ("running", "run", "", False),
    ],
)
def test_alloc_list_stub_is_stuck_failure(
    client_status: str, desired_status: str, next_allocation: str, *, expected: bool
) -> None:
    """Verify only a broken allocation Nomad still wants and has not replaced is stuck."""
    # Given an allocation in the given state
    alloc = alloc_stub(
        client_status=client_status,
        desired_status=desired_status,
        next_allocation=next_allocation,
    )

    # When / Then it is stuck only while broken, wanted, and unreplaced
    assert alloc.is_stuck_failure is expected
