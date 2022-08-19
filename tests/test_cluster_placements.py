# type: ignore
"""Test cluster_placements.py."""

from nd._commands.utils.cluster_placements import Job

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
        "Type": "service",
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
            "task2": {
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


def test_job_class(mocker):
    """Test the Job class."""
    mocker.patch(
        "nd._commands.utils.cluster_placements.make_nomad_api_call",
        return_value=mock_allocation_response,
    )

    jobs = [
        Job("http://junk.url", job["ID"], job["Type"], job["Status"]) for job in mock_jobs_response
    ]
    assert jobs[0].job_id == "job1"
    assert jobs[0].job_type == "service"
    assert jobs[0].status == "pending"
    assert jobs[0].allocations[0].id_num == "36be6d11-cabe-b70f-2a5e-8ddf9a9079fc"
    assert jobs[0].tasks[0].name == "task1"
    assert jobs[0].tasks[1].name == "task2"
    assert jobs[1].job_id == "job2"
