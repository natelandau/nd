"""Tests for job models."""

from __future__ import annotations

import msgspec

from nd.nomad.models.job import Job, JobDeregisterResponse, JobListStub, JobRegisterResponse


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


def test_job_deregister_response_decodes():
    """Verify a job deregister response decodes its eval and index fields."""
    # Given a deregister payload from DELETE /v1/job/:id
    payload = b'{"EvalID": "e1", "EvalCreateIndex": 12, "JobModifyIndex": 34, "Unknown": 1}'

    # When decoding
    resp = msgspec.json.decode(payload, type=JobDeregisterResponse)

    # Then the eval id and indices are populated
    assert resp.eval_id == "e1"
    assert resp.eval_create_index == 12
    assert resp.job_modify_index == 34


def test_job_deregister_response_defaults_empty_eval():
    """Verify a no-op stop response (empty/absent EvalID) decodes to defaults."""
    # Given a payload with a null eval id and no indices
    payload = b'{"EvalID": ""}'

    # When decoding
    resp = msgspec.json.decode(payload, type=JobDeregisterResponse)

    # Then the eval id is empty and indices fall back to zero
    assert resp.eval_id == ""
    assert resp.eval_create_index == 0
    assert resp.job_modify_index == 0


def test_job_register_response_decodes_pascal_keys() -> None:
    """Verify the register response decodes Nomad's PascalCase keys."""
    # Given a Nomad register response body
    payload = b'{"EvalID":"abc","EvalCreateIndex":12,"JobModifyIndex":34,"Warnings":"none"}'
    # When
    resp = msgspec.json.decode(payload, type=JobRegisterResponse)
    # Then
    assert resp.eval_id == "abc"
    assert resp.eval_create_index == 12
    assert resp.job_modify_index == 34
    assert resp.warnings == "none"


def test_job_register_response_tolerates_missing_fields() -> None:
    """Verify a minimal response decodes with defaults."""
    resp = msgspec.json.decode(b"{}", type=JobRegisterResponse)
    assert resp.eval_id == ""
    assert resp.warnings == ""
