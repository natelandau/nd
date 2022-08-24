# type: ignore
"""Shared fixtures and helpers for tests."""

import pytest

from nd._commands.utils import Job, Node


@pytest.fixture()
def mock_nodes():
    """Create list of mock nodes."""
    node1 = Node(
        name="node1",
        id_num="e8b7be25-d438-7ed3-3440-235e6940403f",
        address="10.0.0.4",
        status="ready",
        eligible="eligible",
        datacenter="ny-east",
        node_class="linux",
        version="1.3.3",
    )
    node2 = Node(
        name="node2",
        id_num="e8b7be25-d438-7ed3-3440-l23465jk678k2",
        address="10.0.0.5",
        status="ready",
        eligible="eligible",
        datacenter="ny-east",
        node_class="linux",
        version="1.3.3",
    )
    return [node1, node2]


@pytest.fixture()
def mock_job(mocker):
    """Create list of one mock job."""
    mock_allocation_response = [
        {
            "ID": "36be6d11-cabe-b70f-2a5e-8ddf9a9079fc",
            "EvalID": "233c1977-34e4-e150-2071-cd1dca442823",
            "Name": "mock_job",
            "Namespace": "default",
            "NodeID": "e8b7be25-d438-7ed3-3440-235e6940403f",
            "NodeName": "node1",
            "JobID": "job1",
            "JobType": "service",
            "JobVersion": 0,
            "TaskGroup": "mock_job",
            "TaskStates": {
                "mock_task1": {
                    "State": "running",
                    "Failed": False,
                    "Restarts": 0,
                    "StartedAt": "2022-06-17T12:52:50.059724591Z",
                },
                "mock_task2": {
                    "State": "running",
                    "Failed": False,
                    "Restarts": 0,
                    "StartedAt": "2022-06-17T12:52:50.059724591Z",
                },
            },
            "DeploymentStatus": {
                "Healthy": True,
                "Timestamp": "2022-06-17T08:53:13.918227419-04:00",
                "Canary": False,
                "ModifyIndex": 853045,
            },
        }
    ]

    mocker.patch(
        "nd._commands.utils.cluster_placements.make_nomad_api_call",
        return_value=mock_allocation_response,
    )

    job1 = Job(
        job_id="job1",
        job_type="service",
        status="running",
        create_backup=False,
    )

    return [job1]


@pytest.fixture()
def mock_jobs(mocker):
    """Create list of two mock jobs."""
    mock_allocation_response = [
        {
            "ID": "36be6d11-cabe-b70f-2a5e-8ddf9a9079fc",
            "EvalID": "233c1977-34e4-e150-2071-cd1dca442823",
            "Name": "mock_job",
            "Namespace": "default",
            "NodeID": "e8b7be25-d438-7ed3-3440-235e6940403f",
            "NodeName": "node1",
            "JobID": "job1",
            "JobType": "service",
            "JobVersion": 0,
            "TaskGroup": "mock_job",
            "TaskStates": {
                "mock_task1": {
                    "State": "running",
                    "Failed": False,
                    "Restarts": 0,
                    "StartedAt": "2022-06-17T12:52:50.059724591Z",
                },
                "mock_task2": {
                    "State": "running",
                    "Failed": False,
                    "Restarts": 0,
                    "StartedAt": "2022-06-17T12:52:50.059724591Z",
                },
            },
            "DeploymentStatus": {
                "Healthy": True,
                "Timestamp": "2022-06-17T08:53:13.918227419-04:00",
                "Canary": False,
                "ModifyIndex": 853045,
            },
        }
    ]

    mocker.patch(
        "nd._commands.utils.cluster_placements.make_nomad_api_call",
        return_value=mock_allocation_response,
    )

    job1 = Job(
        job_id="job1",
        job_type="service",
        status="running",
        create_backup=False,
    )

    job2 = Job(
        job_id="job2",
        job_type="service",
        status="running",
        create_backup=True,
    )

    return [job1, job2]


@pytest.fixture()
def mock_whoogle(mocker):
    """Create list of one mock job."""
    mock_allocation_response = [
        {
            "ID": "36be6d11-cabe-b70f-2a5e-8ddf9a9079fc",
            "EvalID": "233c1977-34e4-e150-2071-cd1dca442823",
            "Name": "whoogle",
            "Namespace": "default",
            "NodeID": "e8b7be25-d438-7ed3-3440-235e6940403f",
            "NodeName": "node1",
            "JobID": "job1",
            "JobType": "service",
            "JobVersion": 0,
            "TaskGroup": "whoogle_group",
            "TaskStates": {
                "whoogle": {
                    "State": "running",
                    "Failed": False,
                    "Restarts": 0,
                    "StartedAt": "2022-06-17T12:52:50.059724591Z",
                }
            },
            "DeploymentStatus": {
                "Healthy": True,
                "Timestamp": "2022-06-17T08:53:13.918227419-04:00",
                "Canary": False,
                "ModifyIndex": 853045,
            },
        }
    ]

    mocker.patch(
        "nd._commands.utils.cluster_placements.make_nomad_api_call",
        return_value=mock_allocation_response,
    )

    whoogle = Job(
        job_id="whoogle",
        job_type="service",
        status="running",
        create_backup=False,
    )

    return [whoogle]
