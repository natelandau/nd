"""Tests for agent models and shared helpers."""

import datetime as dt

import msgspec

from nd.nomad.models.agent import AgentSelf
from nd.nomad.models.common import ns_to_datetime


def test_ns_to_datetime_converts_to_aware_utc():
    """Verify ns_to_datetime converts a nanosecond epoch to an aware UTC datetime."""
    # Given a nanosecond-epoch timestamp (1_700_000_000 seconds since the epoch)
    nanos = 1_700_000_000_000_000_000

    # When converting it
    result = ns_to_datetime(nanos)

    # Then the result is the expected aware UTC datetime
    assert result == dt.datetime(2023, 11, 14, 22, 13, 20, tzinfo=dt.UTC)


def test_agent_self_decodes_subset_and_ignores_unknown():
    """Verify AgentSelf decodes the member subset and ignores unknown keys."""
    # Given an agent/self payload with extra top-level sections
    payload = b"""
    {
      "config": {"Region": "global", "Datacenter": "dc1"},
      "member": {"Name": "srv1.global", "Addr": "10.0.0.1", "Status": "alive"},
      "stats": {"nomad": {"leader": "true"}}
    }
    """

    # When decoding it into AgentSelf
    agent = msgspec.json.decode(payload, type=AgentSelf)

    # Then the member fields are populated and unknown sections are ignored
    assert agent.member.name == "srv1.global"
    assert agent.member.addr == "10.0.0.1"
    assert agent.member.status == "alive"
