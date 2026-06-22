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
