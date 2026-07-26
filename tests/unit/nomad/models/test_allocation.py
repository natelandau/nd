"""Tests for allocation models."""

import msgspec

from nd.nomad.models.allocation import Allocation, AllocListStub


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


def test_allocation_decodes_task_states():
    """Verify Allocation decodes task states as a dict of TaskState objects."""
    # Given
    payload = b"""
    {
      "ID": "alloc-1", "Name": "web.web[0]", "Namespace": "default",
      "NodeID": "node-1", "JobID": "web", "TaskGroup": "web",
      "ClientStatus": "running", "DesiredStatus": "run",
      "TaskStates": {
        "server": {"State": "running", "Failed": false, "Restarts": 2}
      },
      "CreateIndex": 7, "ModifyIndex": 11
    }
    """
    # When
    alloc = msgspec.json.decode(payload, type=Allocation)
    # Then
    assert alloc.task_states["server"].state == "running"
    assert alloc.task_states["server"].failed is False
    assert alloc.task_states["server"].restarts == 2


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
