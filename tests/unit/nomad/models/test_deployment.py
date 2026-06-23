"""Tests for deployment models."""

from __future__ import annotations

import msgspec

from nd.nomad.models.deployment import Deployment, DeploymentListStub


def test_deployment_list_stub_decodes():
    """Verify DeploymentListStub decodes a deployment listing stub."""
    # Given a deployment-list stub payload with an unknown extra key
    payload = b"""
    {
      "ID": "dep-1", "JobID": "web", "Namespace": "default",
      "Status": "running", "StatusDescription": "Deployment is running",
      "JobVersion": 3, "CreateIndex": 10, "ModifyIndex": 42,
      "TaskGroups": {"web": {}}
    }
    """
    # When decoding the payload
    stub = msgspec.json.decode(payload, type=DeploymentListStub)

    # Then the typed fields are populated
    assert stub.id == "dep-1"
    assert stub.job_id == "web"
    assert stub.status == "running"
    assert stub.job_version == 3


def test_deployment_decodes_status_and_task_groups() -> None:
    """Verify a deployment decodes status plus per-task-group health counts."""
    # Given a Nomad deployment body
    payload = (
        b'{"ID":"d1","JobID":"web","Status":"running",'
        b'"StatusDescription":"Deployment is running","JobVersion":3,'
        b'"TaskGroups":{"app":{"DesiredTotal":2,"PlacedAllocs":2,'
        b'"HealthyAllocs":1,"UnhealthyAllocs":0}}}'
    )
    # When
    dep = msgspec.json.decode(payload, type=Deployment)
    # Then
    assert dep.id == "d1"
    assert dep.job_id == "web"
    assert dep.status == "running"
    assert dep.task_groups["app"].desired_total == 2
    assert dep.task_groups["app"].healthy_allocs == 1


def test_deployment_tolerates_missing_task_groups() -> None:
    """Verify a deployment without task groups decodes to an empty mapping."""
    payload = b'{"ID":"d2","JobID":"batch","Status":"successful"}'
    dep = msgspec.json.decode(payload, type=Deployment)
    assert dep.task_groups == {}
