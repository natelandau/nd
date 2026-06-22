"""Tests for job models."""

import msgspec

from nd.nomad.models.job import Job, JobListStub


def test_job_list_stub_decodes():
    """Verify job list stub decodes correctly from JSON."""
    # Given
    payload = b"""
    {
      "ID": "web", "Name": "web", "Type": "service", "Status": "running",
      "Priority": 50, "Namespace": "default",
      "CreateIndex": 5, "ModifyIndex": 9, "Unknown": 1
    }
    """

    # When
    stub = msgspec.json.decode(payload, type=JobListStub)

    # Then
    assert stub.id == "web"
    assert stub.type == "service"
    assert stub.priority == 50


def test_job_decodes():
    """Verify job decodes correctly from JSON."""
    # Given
    payload = b"""
    {
      "ID": "web", "Name": "web", "Type": "service", "Status": "running",
      "Priority": 50, "Namespace": "default", "Datacenters": ["dc1", "dc2"],
      "CreateIndex": 5, "ModifyIndex": 9, "Unknown": 2
    }
    """

    # When
    job = msgspec.json.decode(payload, type=Job)

    # Then
    assert job.datacenters == ["dc1", "dc2"]
    assert job.namespace == "default"
