"""Tests for deployment models."""

import msgspec

from nd.nomad.models.deployment import DeploymentListStub


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
