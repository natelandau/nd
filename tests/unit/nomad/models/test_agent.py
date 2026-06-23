"""Tests for agent models and shared helpers."""

import msgspec

from nd.nomad.models.agent import AgentSelf


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
