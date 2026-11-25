"""Tests for deployment models."""

from __future__ import annotations

import msgspec

from nd.nomad.models.deployment import Deployment


def test_deployment_decodes_status_and_task_groups() -> None:
    """Verify a deployment decodes status, indexes, and per-task-group health counts."""
    # Given a Nomad deployment body with an unknown extra key
    payload = (
        b'{"ID":"d1","JobID":"web","Status":"running",'
        b'"StatusDescription":"Deployment is running","JobVersion":3,'
        b'"CreateIndex":10,"ModifyIndex":42,"Unknown":1,'
        b'"TaskGroups":{"app":{"DesiredTotal":2,"PlacedAllocs":2,'
        b'"HealthyAllocs":1,"UnhealthyAllocs":0}}}'
    )
    # When
    dep = msgspec.json.decode(payload, type=Deployment)
    # Then
    assert dep.id == "d1"
    assert dep.job_id == "web"
    assert dep.status == "running"
    assert dep.job_version == 3
    assert dep.create_index == 10
    assert dep.task_groups["app"].desired_total == 2
    assert dep.task_groups["app"].healthy_allocs == 1


def test_deployment_tolerates_missing_task_groups() -> None:
    """Verify a deployment without task groups decodes to an empty mapping."""
    payload = b'{"ID":"d2","JobID":"batch","Status":"successful","CreateIndex":1,"ModifyIndex":2}'
    dep = msgspec.json.decode(payload, type=Deployment)
    assert dep.task_groups == {}
