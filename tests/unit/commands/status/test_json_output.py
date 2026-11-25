"""Tests for the ``nd status --json`` document."""

from __future__ import annotations

import json
from typing import Any

import msgspec
import pytest

from nd.commands.status.json_output import build_status_json
from nd.commands.status.report import HostJobRow, HostPanel, build_report
from nd.nomad.config import NomadConfig
from tests.builders import agent_member, alloc_stub, job_stub, node_stub
from tests.helpers import NOMAD_TEST_ADDR

_CONFIG = NomadConfig(address=NOMAD_TEST_ADDR)


def _encoded(document: msgspec.Struct) -> dict[str, Any]:
    """Round-trip a document through its JSON form, as a script would read it."""
    return json.loads(msgspec.json.encode(document))


def test_build_status_json_reports_effective_and_raw_job_status() -> None:
    """Verify a running job with a stuck failure reads degraded while keeping Nomad's status."""
    # Given a running job whose only allocation failed with no replacement
    report = build_report(
        nodes=[node_stub("n1")],
        jobs=[job_stub("web", status="running")],
        allocs=[alloc_stub("a1", job_id="web", node_id="n1", client_status="failed")],
        config=_CONFIG,
    )

    # When building the JSON document
    document = _encoded(build_status_json(report))

    # Then the job carries both statuses and the verdict is lowercase
    assert document["jobs"] == [
        {
            "id": "web",
            "name": "web",
            "type": "service",
            "status": "degraded",
            "nomad_status": "running",
            "nodes": [],
        }
    ]
    assert document["health"] == "degraded"


def test_build_status_json_lists_server_only_host_with_null_id() -> None:
    """Verify a server with no client node appears as a node with a null ID."""
    # Given a leader server that runs no client agent
    report = build_report(
        nodes=[],
        jobs=[],
        allocs=[],
        config=_CONFIG,
        members=[agent_member("srv1.global", addr="10.0.0.9")],
        leader="10.0.0.9:4647",
    )

    # When building the JSON document
    document = _encoded(build_status_json(report))

    # Then the server is a node row with no ID, and the cluster names it leader
    assert [(n["name"], n["id"], n["role"]) for n in document["nodes"]] == [
        ("srv1", None, "leader")
    ]
    assert document["cluster"]["leader"] == "srv1"


def test_build_status_json_omits_hosts_without_host_panels() -> None:
    """Verify the default view has no hosts key and reports an unset region as null."""
    # Given an empty cluster with no region configured
    report = build_report(nodes=[], jobs=[], allocs=[], config=_CONFIG)

    # When building the JSON document without host panels
    document = _encoded(build_status_json(report))

    # Then there is no hosts key and region is null
    assert "hosts" not in document
    assert document["cluster"]["region"] is None


@pytest.mark.parametrize(
    ("run_start_ns", "expected"),
    [
        pytest.param(1_764_090_000 * 10**9, "2025-11-25T17:00:00Z", id="started"),
        pytest.param(1_764_090_000_123_456_789, "2025-11-25T17:00:00.123456Z", id="sub-second"),
        pytest.param(0, None, id="no-start-time"),
    ],
)
def test_build_status_json_host_started_at(run_start_ns: int, expected: str | None) -> None:
    """Verify a host job's start time is ISO 8601 UTC, or null when Nomad gave none."""
    # Given one host running one job
    report = build_report(nodes=[node_stub("n1")], jobs=[], allocs=[], config=_CONFIG)
    host = HostPanel(
        name="n1",
        link_id="n1",
        address="10.0.0.1",
        status="ready",
        eligible=True,
        version="1.9.0",
        jobs=[
            HostJobRow(
                job_id="web",
                name="web",
                job_type="service",
                group="app",
                status="running",
                run_start_ns=run_start_ns,
            )
        ],
    )

    # When building the JSON document with host panels
    document = _encoded(build_status_json(report, [host]))

    # Then the host's job carries the expected start time
    assert document["hosts"][0]["jobs"][0]["started_at"] == expected
