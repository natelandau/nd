# type: ignore
"""Fixtures for tests."""

import shutil
from pathlib import Path

import pytest
from confz import DataSource, FileSource

from nd.config import NDConfig


@pytest.fixture()
def mock_api_responses():
    """Return a tuple of mock API responses.

    0 = nodes_response
    1 = jobs_response
    2 = allocations_response job 1
    3 = allocations_response job 2
    """
    nodes_response = [
        {
            "Address": "192.168.1.1",
            "ID": "057f9654-0656-073c-8798-fa6204569d2a",
            "Attributes": None,
            "Datacenter": "dc1",
            "Name": "node1",
            "NodeClass": "",
            "Version": "1.4.6",
            "Drain": False,
            "SchedulingEligibility": "eligible",
            "Status": "ready",
            "StatusDescription": "",
            "Drivers": {
                "docker": {
                    "Attributes": {
                        "driver.docker.os_type": "linux",
                        "driver.docker": "true",
                        "driver.docker.version": "23.0.1",
                        "driver.docker.privileged.enabled": "true",
                        "driver.docker.volumes.enabled": "true",
                        "driver.docker.bridge_ip": "172.17.0.1",
                        "driver.docker.runtimes": "io.containerd.runc.v2,runc",
                    },
                    "Detected": True,
                    "Healthy": True,
                    "HealthDescription": "Healthy",
                    "UpdateTime": "2023-03-15T13:14:32.458629957-04:00",
                }
            },
            "HostVolumes": None,
            "NodeResources": None,
            "ReservedResources": None,
            "LastDrain": None,
            "CreateIndex": 994348,
            "ModifyIndex": 1327994,
        },
        {
            "Address": "192.168.1.2",
            "ID": "057f9654-0656-073c-8798-fa6204569d2a",
            "Attributes": None,
            "Datacenter": "dc1",
            "Name": "node2",
            "NodeClass": "",
            "Version": "1.4.6",
            "Drain": False,
            "SchedulingEligibility": "eligible",
            "Status": "ready",
            "StatusDescription": "",
            "Drivers": {
                "docker": {
                    "Attributes": {
                        "driver.docker.os_type": "linux",
                        "driver.docker": "true",
                        "driver.docker.version": "23.0.1",
                        "driver.docker.privileged.enabled": "true",
                        "driver.docker.volumes.enabled": "true",
                        "driver.docker.bridge_ip": "172.17.0.1",
                        "driver.docker.runtimes": "io.containerd.runc.v2,runc",
                    },
                    "Detected": True,
                    "Healthy": True,
                    "HealthDescription": "Healthy",
                    "UpdateTime": "2023-03-15T13:14:32.458629957-04:00",
                }
            },
            "HostVolumes": None,
            "NodeResources": None,
            "ReservedResources": None,
            "LastDrain": None,
            "CreateIndex": 994348,
            "ModifyIndex": 1327994,
        },
    ]
    running_jobs_response = [
        {
            "ID": "job1",
            "ParentID": "",
            "Name": "job1",
            "Namespace": "default",
            "Datacenters": ["dc1"],
            "Multiregion": None,
            "Type": "service",
            "Priority": 50,
            "Periodic": False,
            "ParameterizedJob": False,
            "Stop": False,
            "Status": "running",
            "StatusDescription": "",
            "JobSummary": {
                "JobID": "job1",
                "Namespace": "default",
                "Summary": {
                    "radarrGroup": {
                        "Queued": 0,
                        "Complete": 0,
                        "Failed": 0,
                        "Running": 1,
                        "Starting": 0,
                        "Lost": 0,
                        "Unknown": 0,
                    }
                },
                "Children": {"Pending": 0, "Running": 0, "Dead": 0},
                "CreateIndex": 1329935,
                "ModifyIndex": 1329942,
            },
            "CreateIndex": 1329935,
            "ModifyIndex": 1329947,
            "JobModifyIndex": 1329935,
            "SubmitTime": 1678984359652938453,
            "Meta": None,
        },
        {
            "ID": "job2",
            "ParentID": "",
            "Name": "job2",
            "Namespace": "default",
            "Datacenters": ["dc1"],
            "Multiregion": None,
            "Type": "service",
            "Priority": 50,
            "Periodic": False,
            "ParameterizedJob": False,
            "Stop": False,
            "Status": "running",
            "StatusDescription": "",
            "JobSummary": {
                "JobID": "job2",
                "Namespace": "default",
                "Summary": {
                    "radarrGroup": {
                        "Queued": 0,
                        "Complete": 0,
                        "Failed": 0,
                        "Running": 1,
                        "Starting": 0,
                        "Lost": 0,
                        "Unknown": 0,
                    }
                },
                "Children": {"Pending": 0, "Running": 0, "Dead": 0},
                "CreateIndex": 1329935,
                "ModifyIndex": 1329942,
            },
            "CreateIndex": 1329935,
            "ModifyIndex": 1329947,
            "JobModifyIndex": 1329935,
            "SubmitTime": 1678984359652938453,
            "Meta": None,
        },
    ]
    allocation_response1 = [
        {
            "ID": "4f32c690-75ca-b55c-eb4a-4012dd93cb57",
            "EvalID": "feadbf28-38e8-335d-92ee-a7f1792ff072",
            "Name": "job1.job1Group[0]",
            "Namespace": "default",
            "NodeID": "ebd78455-3ffb-4678-b569-a2b813c31981",
            "NodeName": "node1",
            "JobID": "job1",
            "JobType": "service",
            "JobVersion": 0,
            "TaskGroup": "job1Group",
            "AllocatedResources": None,
            "DesiredStatus": "run",
            "DesiredDescription": "",
            "ClientStatus": "running",
            "ClientDescription": "Tasks are running",
            "DesiredTransition": {
                "Migrate": None,
                "Reschedule": None,
                "ForceReschedule": None,
                "NoShutdownDelay": None,
            },
            "TaskStates": {
                "create_filesystem": {
                    "State": "dead",
                    "Failed": False,
                    "Restarts": 0,
                    "LastRestart": None,
                    "StartedAt": "2023-03-16T16:32:39.926826659Z",
                    "FinishedAt": "2023-03-16T16:32:40.573796601Z",
                    "Events": [
                        {
                            "Type": "Received",
                            "Time": 1678984359711481006,
                            "Message": "",
                            "DisplayMessage": "Task received by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Task Setup",
                            "Time": 1678984359719907763,
                            "Message": "Building Task Directory",
                            "DisplayMessage": "Building Task Directory",
                            "Details": {"message": "Building Task Directory"},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Started",
                            "Time": 1678984359926814993,
                            "Message": "",
                            "DisplayMessage": "Task started by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Terminated",
                            "Time": 1678984360546128139,
                            "Message": "",
                            "DisplayMessage": "Exit Code: 0",
                            "Details": {"oom_killed": "false", "exit_code": "0", "signal": "0"},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                    ],
                    "TaskHandle": None,
                },
                "job1": {
                    "State": "running",
                    "Failed": False,
                    "Restarts": 0,
                    "LastRestart": None,
                    "StartedAt": "2023-03-16T16:32:59.6818882Z",
                    "FinishedAt": None,
                    "Events": [
                        {
                            "Type": "Received",
                            "Time": 1678984359713702888,
                            "Message": "",
                            "DisplayMessage": "Task received by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Task Setup",
                            "Time": 1678984360583576942,
                            "Message": "Building Task Directory",
                            "DisplayMessage": "Building Task Directory",
                            "Details": {"message": "Building Task Directory"},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Driver",
                            "Time": 1678984360653792901,
                            "Message": "",
                            "DisplayMessage": "Downloading image",
                            "Details": {"image": "ghcr.io/linuxserver/job1:develop"},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "Downloading image",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Started",
                            "Time": 1678984379681876071,
                            "Message": "",
                            "DisplayMessage": "Task started by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                    ],
                    "TaskHandle": None,
                },
                "save_configuration": {
                    "State": "pending",
                    "Failed": False,
                    "Restarts": 0,
                    "LastRestart": None,
                    "StartedAt": None,
                    "FinishedAt": None,
                    "Events": [
                        {
                            "Type": "Received",
                            "Time": 1678984359714048881,
                            "Message": "",
                            "DisplayMessage": "Task received by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        }
                    ],
                    "TaskHandle": None,
                },
            },
            "DeploymentStatus": {
                "Healthy": True,
                "Timestamp": "2023-03-16T12:33:42.722795231-04:00",
                "Canary": False,
                "ModifyIndex": 1329945,
            },
            "FollowupEvalID": "",
            "RescheduleTracker": None,
            "PreemptedAllocations": None,
            "PreemptedByAllocation": "",
            "CreateIndex": 1329936,
            "ModifyIndex": 1329945,
            "CreateTime": 1678984359673508970,
            "ModifyTime": 1678984422931353235,
        }
    ]
    allocation_response2 = [
        {
            "ID": "4f32c690-75ca-b55c-eb4a-4012dd93cb57",
            "EvalID": "feadbf28-38e8-335d-92ee-a7f1792ff072",
            "Name": "job1.job1Group[0]",
            "Namespace": "default",
            "NodeID": "ebd78455-3ffb-4678-b569-a2b813c31981",
            "NodeName": "node2",
            "JobID": "job2",
            "JobType": "service",
            "JobVersion": 0,
            "TaskGroup": "job2Group",
            "AllocatedResources": None,
            "DesiredStatus": "run",
            "DesiredDescription": "",
            "ClientStatus": "running",
            "ClientDescription": "Tasks are running",
            "DesiredTransition": {
                "Migrate": None,
                "Reschedule": None,
                "ForceReschedule": None,
                "NoShutdownDelay": None,
            },
            "TaskStates": {
                "create_filesystem": {
                    "State": "dead",
                    "Failed": False,
                    "Restarts": 0,
                    "LastRestart": None,
                    "StartedAt": "2023-03-16T16:32:39.926826659Z",
                    "FinishedAt": "2023-03-16T16:32:40.573796601Z",
                    "Events": [
                        {
                            "Type": "Received",
                            "Time": 1678984359711481006,
                            "Message": "",
                            "DisplayMessage": "Task received by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Task Setup",
                            "Time": 1678984359719907763,
                            "Message": "Building Task Directory",
                            "DisplayMessage": "Building Task Directory",
                            "Details": {"message": "Building Task Directory"},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Started",
                            "Time": 1678984359926814993,
                            "Message": "",
                            "DisplayMessage": "Task started by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Terminated",
                            "Time": 1678984360546128139,
                            "Message": "",
                            "DisplayMessage": "Exit Code: 0",
                            "Details": {"oom_killed": "false", "exit_code": "0", "signal": "0"},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                    ],
                    "TaskHandle": None,
                },
                "job2": {
                    "State": "running",
                    "Failed": False,
                    "Restarts": 0,
                    "LastRestart": None,
                    "StartedAt": "2023-03-16T16:32:59.6818882Z",
                    "FinishedAt": None,
                    "Events": [
                        {
                            "Type": "Received",
                            "Time": 1678984359713702888,
                            "Message": "",
                            "DisplayMessage": "Task received by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Task Setup",
                            "Time": 1678984360583576942,
                            "Message": "Building Task Directory",
                            "DisplayMessage": "Building Task Directory",
                            "Details": {"message": "Building Task Directory"},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Driver",
                            "Time": 1678984360653792901,
                            "Message": "",
                            "DisplayMessage": "Downloading image",
                            "Details": {"image": "ghcr.io/linuxserver/job1:develop"},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "Downloading image",
                            "GenericSource": "",
                        },
                        {
                            "Type": "Started",
                            "Time": 1678984379681876071,
                            "Message": "",
                            "DisplayMessage": "Task started by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        },
                    ],
                    "TaskHandle": None,
                },
                "save_configuration": {
                    "State": "pending",
                    "Failed": False,
                    "Restarts": 0,
                    "LastRestart": None,
                    "StartedAt": None,
                    "FinishedAt": None,
                    "Events": [
                        {
                            "Type": "Received",
                            "Time": 1678984359714048881,
                            "Message": "",
                            "DisplayMessage": "Task received by client",
                            "Details": {},
                            "FailsTask": False,
                            "RestartReason": "",
                            "SetupError": "",
                            "DriverError": "",
                            "ExitCode": 0,
                            "Signal": 0,
                            "KillTimeout": 0,
                            "KillError": "",
                            "KillReason": "",
                            "StartDelay": 0,
                            "DownloadError": "",
                            "ValidationError": "",
                            "DiskLimit": 0,
                            "FailedSibling": "",
                            "VaultError": "",
                            "TaskSignalReason": "",
                            "TaskSignal": "",
                            "DriverMessage": "",
                            "GenericSource": "",
                        }
                    ],
                    "TaskHandle": None,
                },
            },
            "DeploymentStatus": {
                "Healthy": True,
                "Timestamp": "2023-03-16T12:33:42.722795231-04:00",
                "Canary": False,
                "ModifyIndex": 1329945,
            },
            "FollowupEvalID": "",
            "RescheduleTracker": None,
            "PreemptedAllocations": None,
            "PreemptedByAllocation": "",
            "CreateIndex": 1329936,
            "ModifyIndex": 1329945,
            "CreateTime": 1678984359673508970,
            "ModifyTime": 1678984422931353235,
        }
    ]

    return nodes_response, running_jobs_response, allocation_response1, allocation_response2


@pytest.fixture()
def job_dir(tmp_path) -> Path:
    """Fixture for a job directory.

    Creates a directory containing three valid job files and one invalid job file.

    Returns:
        Path: Path to the job directory.
    """
    job_dir = Path(tmp_path / "job_dir")
    job_dir.mkdir()

    for i in range(1, 4):
        src_file = Path("tests/fixtures/jobfile_valid.hcl")
        if src_file.is_file():
            dest_file = Path(job_dir / f"job{i}.hcl")
            shutil.copy(src_file, dest_file)
        else:
            print(f"File {src_file} does not exist. Skipping copy.")

    shutil.copy(Path("tests/fixtures/jobfile_invalid.hcl"), job_dir / "invalid.hcl")

    return job_dir


@pytest.fixture()
def mock_config(tmp_path) -> Path:  # noqa: PT004
    """Fixture to create a mock configuration file and mock job directory for testing.

    Paths include a valid and an invalid path
    Files in the job directory include a valid files, an invalid file, and a file that should be ignored.


    Returns:
        Config: Config object with the mock configuration.
    """
    job_dir = Path(tmp_path / "job_dir")
    job_dir.mkdir()

    for i in range(1, 4):
        src_file = Path("tests/fixtures/jobfile_valid.hcl")
        if src_file.is_file():
            dest_file = Path(job_dir / f"job{i}.hcl")
            shutil.copy(src_file, dest_file)

    shutil.copy(Path("tests/fixtures/jobfile_invalid.hcl"), job_dir / "invalid.hcl")
    shutil.copy(Path("tests/fixtures/jobfile_valid.hcl"), job_dir / "i_am_ignored.hcl")

    config_text = f"""
file_ignore_strings = ["ignore"]
job_file_locations = ["{job_dir}", "/path/does/not/exist"]
nomad_address = 'https://127.0.0.1:4646/'

    """
    path_to_config = Path(tmp_path / "config.toml")
    path_to_config.write_text(config_text)

    with NDConfig.change_config_sources([FileSource(path_to_config)]):
        yield


@pytest.fixture()
def mock_specific_config():
    """Mock specific configuration data for use in tests."""

    def _inner(
        tmp_path,
        file_ignore_strings: list[str] | None = None,
        job_file_locations: list[str] | None = None,
        nomad_address: str | None = None,
    ):
        override_data = {}
        if file_ignore_strings:
            override_data["file_ignore_strings"] = file_ignore_strings
        if job_file_locations:
            override_data["job_file_locations"] = job_file_locations
        if nomad_address:
            override_data["nomad_address"] = nomad_address

        job_dir = Path(tmp_path / "job_dir")
        job_dir.mkdir()

        for i in range(1, 4):
            src_file = Path("tests/fixtures/jobfile_valid.hcl")
            if src_file.is_file():
                dest_file = Path(job_dir / f"job{i}.hcl")
                shutil.copy(src_file, dest_file)

        shutil.copy(Path("tests/fixtures/jobfile_invalid.hcl"), job_dir / "invalid.hcl")
        shutil.copy(Path("tests/fixtures/jobfile_valid.hcl"), job_dir / "i_am_ignored.hcl")

        config_text = f"""
    file_ignore_strings = ["ignore"]
    job_file_locations = ["{job_dir}", "/path/does/not/exist"]
    nomad_address = 'https://127.0.0.1:4646/'

        """
        path_to_config = Path(tmp_path / "config.toml")
        path_to_config.write_text(config_text)

        return [FileSource(path_to_config), DataSource(data=override_data)]

    return _inner
