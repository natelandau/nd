# type: ignore
"""Test cluster_placements.py."""

import re

from nd._utils.cluster_placements import Job, populate_running_jobs

mock_jobs_response = [
    {
        "ID": "job1",
        "ParentID": "",
        "Name": "job1",
        "Type": "service",
        "Priority": 50,
        "Status": "pending",
    },
    {
        "ID": "job2",
        "ParentID": "",
        "Name": "job2",
        "Type": "sysbatch",
        "Priority": 50,
        "Status": "pending",
    },
]

mock_allocation_response = [
    {
        "ID": "36be6d11-cabe-b70f-2a5e-8ddf9a9079fc",
        "EvalID": "233c1977-34e4-e150-2071-cd1dca442823",
        "Name": "job1.job1[0]",
        "Namespace": "default",
        "NodeID": "7828a67f-d9c5-9179-ce33-871af4b9bf2b",
        "NodeName": "node1",
        "JobID": "job1",
        "JobType": "service",
        "JobVersion": 0,
        "TaskGroup": "job1",
        "TaskStates": {
            "task1": {
                "State": "running",
                "Failed": False,
                "Restarts": 0,
                "StartedAt": "2022-06-17T12:52:50.059724591Z",
            },
            "create_filesystem": {
                "State": "running",
                "Failed": False,
                "Restarts": 0,
                "StartedAt": "",
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


def test_job_class(requests_mock):
    """Test the Job class."""
    allocations_url = re.compile(r".*/job/.*/allocations$")
    requests_mock.get(allocations_url, json=mock_allocation_response)

    jobs = [
        Job("http://junk.url", job["ID"], job["Type"], job["Status"]) for job in mock_jobs_response
    ]
    assert jobs[0].job_id == "job1"
    assert jobs[0].job_type == "service"
    assert jobs[0].status == "pending"
    assert jobs[0].allocations[0].id_num == "36be6d11-cabe-b70f-2a5e-8ddf9a9079fc"
    assert jobs[0].allocations[0].healthy is True
    assert jobs[0].tasks[0].name == "task1"
    assert jobs[0].tasks[1].name == "create_filesystem"
    assert jobs[0].create_backup is True
    assert jobs[1].job_id == "job2"
    assert jobs[1].job_type == "sysbatch"
    assert jobs[1].status == "pending"
    assert jobs[1].allocations[0].healthy is True


def test_populate_running_jobs(
    requests_mock,
):
    """Test the populate_running_jobs function."""
    jobs_url = re.compile(r".*/jobs$")
    allocations_url = re.compile(r".*/job/.*/allocations$")
    requests_mock.get(jobs_url, json=mock_jobs_response)
    requests_mock.get(allocations_url, json=mock_allocation_response)

    jobs = populate_running_jobs("http://junk.url")
    assert jobs[0].job_id == "job1"
    assert jobs[0].job_type == "service"
    assert jobs[0].status == "pending"
    assert jobs[1].job_id == "job2"
    assert jobs[1].job_type == "sysbatch"
    assert jobs[1].status == "pending"

    requests_mock.get(jobs_url, json=[])
    jobs = populate_running_jobs("http://junk.url")
    assert jobs == []
