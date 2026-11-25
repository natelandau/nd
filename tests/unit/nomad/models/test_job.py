"""Tests for job models."""

from __future__ import annotations

import msgspec

from nd.nomad.models.job import (
    JobDeregisterResponse,
    JobListStub,
    JobRegisterResponse,
    JobSpec,
)


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


def test_job_spec_decodes_full_api_job():
    """Verify a full job from the API decodes the fields the health checks read."""
    # Given a job shaped like the GET /v1/job/:job_id response
    payload = b"""
    {
      "ID": "web", "Name": "web", "Type": "service", "Status": "running",
      "TaskGroups": [{
        "Name": "web",
        "Services": [{"Name": "web", "Checks": [{"Name": "alive", "Type": "http"}]}],
        "Volumes": {"data": {"Type": "host", "Source": "data"}},
        "Tasks": [{
          "Name": "app", "Driver": "docker",
          "Config": {"image": "nginx:1.27", "ports": ["http"]},
          "Resources": {"CPU": 500, "MemoryMB": 512}
        }]
      }]
    }
    """

    # When
    spec = msgspec.json.decode(payload, type=JobSpec)

    # Then
    group = spec.task_groups[0]
    task = group.tasks[0]
    assert spec.name == "web"
    assert spec.status == "running"
    assert group.volumes["data"].source == "data"
    assert len(group.services[0].checks) == 1
    assert task.config["image"] == "nginx:1.27"
    assert task.resources is not None
    assert task.resources.cpu == 500
    assert task.resources.memory_mb == 512


def test_job_spec_reads_nulls_as_empty():
    """Verify Nomad's explicit nulls in a job spec decode as empty or unset."""
    # Given a job whose nested collections and optional scalars are all null
    payload = b"""
    {
      "ID": "web", "Name": "web", "Type": null, "Status": null, "ParentID": null,
      "TaskGroups": [{
        "Name": "web", "Services": null,
        "Volumes": {"data": {"Type": null, "Source": null}},
        "Tasks": [{"Name": "app", "Driver": null, "Config": null,
                   "Resources": {"CPU": null, "MemoryMB": null},
                   "Services": [{"Name": null, "Checks": null}]}]
      }]
    }
    """

    # When
    spec = msgspec.json.decode(payload, type=JobSpec)

    # Then
    group = spec.task_groups[0]
    task = group.tasks[0]
    assert spec.status is None
    assert group.services == []
    assert group.volumes["data"].source is None
    assert task.config == {}
    assert task.resources is not None
    assert task.resources.cpu is None
    assert task.services[0].checks == []
    assert msgspec.json.decode(b'{"TaskGroups": null}', type=JobSpec).task_groups == []
