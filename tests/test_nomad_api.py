# type: ignore
"""Test the Nomad API."""

import pytest
import requests

from nd._commands.utils.call_nomad_api import make_nomad_api_call

valid_json = {
    "Address": "10.138.0.5",
    "Attributes": {"os.name": "ubuntu"},
    "CreateIndex": 6,
    "Datacenter": "dc1",
    "ID": "f7476465-4d6e-c0de-26d0-e383c49be941",
    "ModifyIndex": 2526,
    "Name": "nomad-4",
    "NodeClass": "",
    "SchedulingEligibility": "eligible",
    "Status": "ready",
    "StatusDescription": "",
    "Version": "0.8.0-rc1",
}


def test_nomad_api_call_valid_json(requests_mock):
    """Test a valid response from the Nomad API."""
    requests_mock.get("http://fake.url", json=valid_json)
    response = make_nomad_api_call("http://fake.url", "get")
    assert response["Address"] == "10.138.0.5"
    assert response["Attributes"]["os.name"] == "ubuntu"


def test_nomad_api_call_no_json(requests_mock) -> None:
    """Test a valid response from the Nomad API."""
    requests_mock.get("http://fake.url", text="")
    assert make_nomad_api_call("http://fake.url", "get") is True


def test_connection_error(requests_mock):
    """Test a connection error."""
    requests_mock.get("http://fake.url", status_code=404)

    with pytest.raises(SystemExit):
        make_nomad_api_call("http://fake.url", "get")


def test_json_value_error(requests_mock):
    """Test a JSON decode error."""
    requests_mock.get("http://fake.url", text="not json")

    with pytest.raises(SystemExit):
        make_nomad_api_call("http://fake.url", "get")


def test_json_decode_error(requests_mock):
    """Test a JSON decode error."""
    requests_mock.get("http://fake.url", exc=requests.exceptions.JSONDecodeError("test", "test", 0))

    with pytest.raises(SystemExit):
        make_nomad_api_call("http://fake.url", "get")
